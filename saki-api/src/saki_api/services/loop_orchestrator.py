"""
Background orchestrator for active-learning loops.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, UTC

from sqlmodel import select, func

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models.enums import (
    ALLoopStatus,
    LoopRoundStatus,
    AnnotationBatchStatus,
    TrainingJobStatus,
)
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.loop_round import LoopRound
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.model import Model

logger = logging.getLogger(__name__)


class LoopOrchestrator:
    def __init__(self, interval_sec: int | None = None) -> None:
        self.interval_sec = max(2, int(interval_sec or settings.RUNTIME_DISPATCH_INTERVAL_SEC))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="loop-orchestrator")
        logger.info("loop orchestrator started interval=%ss", self.interval_sec)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("loop orchestrator stopped")

    async def tick_once(self) -> None:
        await self._tick()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("loop orchestrator tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_sec)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        async with SessionLocal() as session:
            rows = await session.exec(
                select(ALLoop.id).where(
                    ALLoop.is_active.is_(True),
                    ALLoop.status == ALLoopStatus.RUNNING,
                )
            )
            loop_ids = list(rows.all())

        for loop_id in loop_ids:
            await self._process_loop(loop_id)

    async def _process_loop(self, loop_id: uuid.UUID) -> None:
        dispatch_job_id: uuid.UUID | None = None
        async with SessionLocal() as session:
            loop = await session.get(ALLoop, loop_id)
            if not loop or loop.status != ALLoopStatus.RUNNING or not loop.is_active:
                return

            branch = await session.get(Branch, loop.branch_id)
            if not branch:
                loop.status = ALLoopStatus.FAILED
                loop.last_error = f"branch {loop.branch_id} not found"
                session.add(loop)
                await session.commit()
                return

            latest_round = await self._latest_round(session, loop.id)
            if not latest_round:
                seed_count = await self._count_labeled_samples(session, branch.head_commit_id)
                if seed_count >= loop.min_seed_labeled:
                    dispatch_job_id = await self._create_round_job(
                        session=session,
                        loop=loop,
                        source_commit_id=branch.head_commit_id,
                    )
                    await session.commit()
                return

            if latest_round.status == LoopRoundStatus.TRAINING:
                dispatch_job_id = await self._handle_training_round(
                    session=session,
                    loop=loop,
                    round_obj=latest_round,
                    branch=branch,
                )
                await session.commit()
            elif latest_round.status == LoopRoundStatus.ANNOTATION:
                dispatch_job_id = await self._handle_annotation_round(
                    session=session,
                    loop=loop,
                    round_obj=latest_round,
                    branch=branch,
                )
                await session.commit()

        if dispatch_job_id:
            async with SessionLocal() as session:
                job = await session.get(Job, dispatch_job_id)
                if job:
                    assigned = await runtime_dispatcher.assign_job(job)
                    if not assigned:
                        await runtime_dispatcher.dispatch_pending_jobs()

    async def _latest_round(self, session, loop_id: uuid.UUID) -> LoopRound | None:
        rows = await session.exec(
            select(LoopRound)
            .where(LoopRound.loop_id == loop_id)
            .order_by(LoopRound.round_index.desc(), LoopRound.created_at.desc())
            .limit(1)
        )
        return rows.first()

    async def _count_labeled_samples(self, session, commit_id: uuid.UUID) -> int:
        row = await session.exec(
            select(func.count(func.distinct(CommitAnnotationMap.sample_id)))
            .where(CommitAnnotationMap.commit_id == commit_id)
        )
        return int(row.one() or 0)

    async def _create_round_job(
            self,
            *,
            session,
            loop: ALLoop,
            source_commit_id: uuid.UUID,
    ) -> uuid.UUID:
        loop.current_iteration += 1
        round_index = int(loop.current_iteration)

        params = dict(loop.global_config or {})
        params.setdefault("topk", loop.query_batch_size)
        job = Job(
            project_id=loop.project_id,
            loop_id=loop.id,
            iteration=round_index,
            round_index=round_index,
            status=TrainingJobStatus.PENDING,
            source_commit_id=source_commit_id,
            job_type="train_detection",
            plugin_id=loop.model_arch,
            mode="active_learning",
            query_strategy=loop.query_strategy,
            params=params,
            resources={},
            strategy_params={},
            metrics={},
            artifacts={},
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)

        round_obj = LoopRound(
            loop_id=loop.id,
            round_index=round_index,
            source_commit_id=source_commit_id,
            job_id=job.id,
            status=LoopRoundStatus.TRAINING,
            metrics={},
            selected_count=0,
            labeled_count=0,
            started_at=datetime.now(UTC),
        )
        session.add(round_obj)
        loop.last_job_id = job.id
        loop.last_error = None
        session.add(loop)
        return job.id

    async def _handle_training_round(
            self,
            *,
            session,
            loop: ALLoop,
            round_obj: LoopRound,
            branch: Branch,
    ) -> uuid.UUID | None:
        if not round_obj.job_id:
            round_obj.status = LoopRoundStatus.FAILED
            loop.status = ALLoopStatus.FAILED
            loop.last_error = "round has no job_id"
            session.add(round_obj)
            session.add(loop)
            return None

        job = await session.get(Job, round_obj.job_id)
        if not job:
            round_obj.status = LoopRoundStatus.FAILED
            loop.status = ALLoopStatus.FAILED
            loop.last_error = f"job {round_obj.job_id} not found"
            session.add(round_obj)
            session.add(loop)
            return None

        if job.status in {TrainingJobStatus.PENDING, TrainingJobStatus.RUNNING}:
            return None
        if job.status != TrainingJobStatus.SUCCESS:
            round_obj.status = LoopRoundStatus.FAILED
            round_obj.ended_at = datetime.now(UTC)
            loop.status = ALLoopStatus.FAILED
            loop.last_error = job.last_error or f"job failed: {job.status}"
            session.add(round_obj)
            session.add(loop)
            return None

        batch = await self._create_annotation_batch(session=session, loop=loop, job=job)
        round_obj.annotation_batch_id = batch.id
        round_obj.metrics = dict(job.metrics or {})
        round_obj.selected_count = int(batch.total_count)
        round_obj.status = LoopRoundStatus.ANNOTATION
        session.add(round_obj)

        if loop.auto_register_model:
            model = await self._register_model(session=session, loop=loop, job=job)
            if model:
                job.model_id = model.id
                loop.latest_model_id = model.id
                session.add(job)
        session.add(loop)
        return None

    async def _create_annotation_batch(self, *, session, loop: ALLoop, job: Job) -> AnnotationBatch:
        existing_rows = await session.exec(select(AnnotationBatch).where(AnnotationBatch.job_id == job.id))
        existing = existing_rows.first()
        if existing:
            return existing

        metric_rows = await session.exec(
            select(JobSampleMetric)
            .where(JobSampleMetric.job_id == job.id)
            .order_by(JobSampleMetric.score.desc())
            .limit(loop.query_batch_size)
        )
        candidates = list(metric_rows.all())
        batch = AnnotationBatch(
            project_id=loop.project_id,
            loop_id=loop.id,
            job_id=job.id,
            round_index=max(1, int(job.round_index or job.iteration or 1)),
            status=AnnotationBatchStatus.OPEN,
            total_count=len(candidates),
            annotated_count=0,
            meta={"source": "orchestrator"},
        )
        session.add(batch)
        await session.flush()
        await session.refresh(batch)

        for idx, item in enumerate(candidates, start=1):
            session.add(
                AnnotationBatchItem(
                    batch_id=batch.id,
                    sample_id=item.sample_id,
                    rank=idx,
                    score=float(item.score),
                    reason=dict(item.extra or {}),
                    prediction_snapshot=dict(item.prediction_snapshot or {}),
                )
            )
        return batch

    async def _handle_annotation_round(
            self,
            *,
            session,
            loop: ALLoop,
            round_obj: LoopRound,
            branch: Branch,
    ) -> uuid.UUID | None:
        if not round_obj.annotation_batch_id:
            round_obj.status = LoopRoundStatus.FAILED
            loop.status = ALLoopStatus.FAILED
            loop.last_error = "round has no annotation batch"
            session.add(round_obj)
            session.add(loop)
            return None

        batch = await session.get(AnnotationBatch, round_obj.annotation_batch_id)
        if not batch:
            round_obj.status = LoopRoundStatus.FAILED
            loop.status = ALLoopStatus.FAILED
            loop.last_error = f"annotation batch {round_obj.annotation_batch_id} not found"
            session.add(round_obj)
            session.add(loop)
            return None

        await self._refresh_batch_progress(
            session=session,
            batch=batch,
            commit_id=branch.head_commit_id,
        )
        round_obj.labeled_count = int(batch.annotated_count)
        session.add(round_obj)

        can_advance = (
                batch.annotated_count >= loop.min_new_labels_per_round
                or batch.status == AnnotationBatchStatus.CLOSED
        )
        if not can_advance:
            return None

        round_obj.status = LoopRoundStatus.COMPLETED
        round_obj.ended_at = datetime.now(UTC)
        session.add(round_obj)

        if round_obj.round_index >= loop.max_rounds or await self._should_early_stop(session=session, loop=loop):
            loop.status = ALLoopStatus.COMPLETED
            loop.is_active = False
            session.add(loop)
            return None

        if branch.head_commit_id == round_obj.source_commit_id:
            # Wait for a new commit (human annotation commit) before launching next round.
            return None

        return await self._create_round_job(
            session=session,
            loop=loop,
            source_commit_id=branch.head_commit_id,
        )

    async def _refresh_batch_progress(self, *, session, batch: AnnotationBatch, commit_id: uuid.UUID) -> None:
        rows = await session.exec(
            select(AnnotationBatchItem).where(AnnotationBatchItem.batch_id == batch.id)
        )
        items = list(rows.all())
        if not items:
            batch.annotated_count = 0
            batch.status = AnnotationBatchStatus.CLOSED
            batch.closed_at = datetime.now(UTC)
            session.add(batch)
            return

        sample_ids = [item.sample_id for item in items]
        camap_rows = await session.exec(
            select(CommitAnnotationMap.sample_id)
            .where(
                CommitAnnotationMap.commit_id == commit_id,
                CommitAnnotationMap.sample_id.in_(sample_ids),
            )
            .distinct()
        )
        annotated = {row for row in camap_rows.all()}
        now = datetime.now(UTC)
        for item in items:
            should_annotated = item.sample_id in annotated
            if should_annotated and not item.is_annotated:
                item.is_annotated = True
                item.annotated_at = now
                session.add(item)

        batch.annotated_count = len(annotated)
        if batch.annotated_count >= batch.total_count and batch.total_count > 0:
            batch.status = AnnotationBatchStatus.CLOSED
            if not batch.closed_at:
                batch.closed_at = now
        session.add(batch)

    async def _should_early_stop(self, *, session, loop: ALLoop) -> bool:
        rounds_rows = await session.exec(
            select(LoopRound)
            .where(
                LoopRound.loop_id == loop.id,
                LoopRound.status == LoopRoundStatus.COMPLETED,
            )
            .order_by(LoopRound.round_index.desc())
            .limit(loop.stop_patience_rounds + 1)
        )
        rounds = list(rounds_rows.all())
        if len(rounds) < loop.stop_patience_rounds + 1:
            return False
        rounds_sorted = sorted(rounds, key=lambda item: item.round_index)
        first_map = float((rounds_sorted[0].metrics or {}).get("map50") or 0.0)
        last_map = float((rounds_sorted[-1].metrics or {}).get("map50") or 0.0)
        return (last_map - first_map) < float(loop.stop_min_gain or 0.0)

    async def _register_model(self, *, session, loop: ALLoop, job: Job) -> Model | None:
        artifact_map = dict(job.artifacts or {})
        if not artifact_map:
            return None
        weights_path = ""
        if "best.pt" in artifact_map and isinstance(artifact_map["best.pt"], dict):
            weights_path = str(artifact_map["best.pt"].get("uri") or "")
        if not weights_path:
            for _, item in artifact_map.items():
                if isinstance(item, dict) and str(item.get("kind") or "").lower() == "weights":
                    weights_path = str(item.get("uri") or "")
                    if weights_path:
                        break
        if not weights_path:
            return None

        model = Model(
            project_id=loop.project_id,
            job_id=job.id,
            source_commit_id=job.source_commit_id,
            plugin_id=job.plugin_id,
            model_arch=loop.model_arch,
            name=f"{loop.name}-round-{job.round_index}",
            version_tag=f"r{job.round_index}",
            weights_path=weights_path,
            status="candidate",
            metrics=dict(job.metrics or {}),
            artifacts=artifact_map,
        )
        session.add(model)
        await session.flush()
        await session.refresh(model)
        return model


loop_orchestrator = LoopOrchestrator()
