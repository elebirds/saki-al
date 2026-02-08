"""
Background orchestrator for active-learning loops.
"""

from __future__ import annotations

import asyncio
from loguru import logger
import uuid
from datetime import datetime, UTC

from sqlmodel import select, func

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
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
from saki_api.services.annotation_batch_progress import refresh_batch_progress_by_commit
from saki_api.services.loop_config import (
    normalize_loop_global_config,
    round_split_seed,
    to_bool,
    to_int,
)
from saki_api.utils.storage import get_storage_provider



class LoopOrchestrator:
    def __init__(self, interval_sec: int | None = None, session_local=SessionLocal) -> None:
        self.interval_sec = max(2, int(interval_sec or settings.RUNTIME_DISPATCH_INTERVAL_SEC))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._storage = None
        self._session_local = session_local

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="loop-orchestrator")
        logger.info("主动学习编排器已启动 interval_sec={}", self.interval_sec)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("主动学习编排器已停止")

    async def tick_once(self) -> None:
        await self._tick()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("主动学习编排器轮询失败 error={}", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_sec)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        async with self._session_local() as session:
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
        async with self._session_local() as session:
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
            await self._dispatch_job(dispatch_job_id)

    @staticmethod
    def _validate_recover_mode(mode: str) -> None:
        if mode not in {"retry_same_params", "rerun_with_overrides"}:
            raise BadRequestAppException(f"invalid recover mode: {mode}")

    async def _find_active_round_job(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            round_index: int,
    ) -> Job | None:
        rows = await session.exec(
            select(Job)
            .where(
                Job.loop_id == loop_id,
                Job.round_index == round_index,
                Job.status.in_([TrainingJobStatus.PENDING, TrainingJobStatus.RUNNING]),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return rows.first()

    @staticmethod
    def _mark_recovered_round_and_loop(
            *,
            loop: ALLoop,
            round_obj: LoopRound,
            job_id: uuid.UUID,
            start_now: bool,
    ) -> None:
        round_obj.status = LoopRoundStatus.TRAINING
        round_obj.job_id = job_id
        round_obj.ended_at = None
        if start_now:
            round_obj.started_at = datetime.now(UTC)
        elif round_obj.started_at is None:
            round_obj.started_at = datetime.now(UTC)
        loop.status = ALLoopStatus.RUNNING
        loop.is_active = True
        loop.last_error = None
        loop.last_job_id = job_id

    @staticmethod
    def _ensure_recoverable_state(*, loop: ALLoop, latest_round: LoopRound) -> None:
        if latest_round.status != LoopRoundStatus.FAILED and loop.status != ALLoopStatus.FAILED:
            raise BadRequestAppException("loop latest round is not failed")

    async def _find_failed_round_job(
            self,
            *,
            session,
            loop: ALLoop,
            latest_round: LoopRound,
    ) -> Job | None:
        if latest_round.job_id:
            job = await session.get(Job, latest_round.job_id)
            if job and job.status == TrainingJobStatus.FAILED:
                return job
        rows = await session.exec(
            select(Job)
            .where(
                Job.loop_id == loop.id,
                Job.round_index == latest_round.round_index,
                Job.status == TrainingJobStatus.FAILED,
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return rows.first()

    @staticmethod
    def _resolve_recover_job_config(
            *,
            failed_job: Job,
            mode: str,
            overrides: dict[str, object] | None,
    ) -> tuple[str, str, dict[str, object], dict[str, object]]:
        params = dict(failed_job.params or {})
        resources = dict(failed_job.resources or {})
        plugin_id = str(failed_job.plugin_id or "")
        query_strategy = str(failed_job.query_strategy or "")

        if mode == "rerun_with_overrides":
            payload = dict(overrides or {})
            override_query_strategy = payload.get("query_strategy")
            if override_query_strategy is not None:
                query_strategy = str(override_query_strategy or "")
            override_plugin_id = payload.get("plugin_id")
            if override_plugin_id is not None:
                plugin_id = str(override_plugin_id or "")

            override_params = payload.get("params")
            if override_params is not None:
                if not isinstance(override_params, dict):
                    raise BadRequestAppException("overrides.params must be an object")
                params = dict(override_params)

            override_resources = payload.get("resources")
            if override_resources is not None:
                if not isinstance(override_resources, dict):
                    raise BadRequestAppException("overrides.resources must be an object")
                resources = dict(override_resources)

        if not plugin_id:
            raise BadRequestAppException("plugin_id is required for recover")
        if not query_strategy:
            raise BadRequestAppException("query_strategy is required for recover")
        return plugin_id, query_strategy, params, resources

    @staticmethod
    def _build_recovered_job(
            *,
            failed_job: Job,
            latest_round: LoopRound,
            plugin_id: str,
            query_strategy: str,
            params: dict[str, object],
            resources: dict[str, object],
    ) -> Job:
        return Job(
            project_id=failed_job.project_id,
            loop_id=failed_job.loop_id,
            iteration=int(failed_job.iteration or latest_round.round_index),
            round_index=int(failed_job.round_index or latest_round.round_index),
            status=TrainingJobStatus.PENDING,
            source_commit_id=failed_job.source_commit_id,
            job_type=failed_job.job_type,
            plugin_id=plugin_id,
            mode=failed_job.mode,
            query_strategy=query_strategy,
            params=params,
            resources=resources,
            strategy_params=dict(failed_job.strategy_params or {}),
            metrics={},
            artifacts={},
        )

    async def recover_failed_loop(
            self,
            *,
            loop_id: uuid.UUID,
            mode: str,
            overrides: dict[str, object] | None,
    ) -> uuid.UUID:
        self._validate_recover_mode(mode)

        dispatch_job_id: uuid.UUID | None = None
        async with self._session_local() as session:
            loop = await session.get(ALLoop, loop_id)
            if not loop:
                raise BadRequestAppException(f"Loop {loop_id} not found")

            latest_round = await self._latest_round(session, loop.id)
            if not latest_round:
                raise BadRequestAppException("loop has no round to recover")

            active_job = await self._find_active_round_job(
                session=session,
                loop_id=loop.id,
                round_index=latest_round.round_index,
            )
            if active_job:
                self._mark_recovered_round_and_loop(
                    loop=loop,
                    round_obj=latest_round,
                    job_id=active_job.id,
                    start_now=False,
                )
                session.add(latest_round)
                session.add(loop)
                await session.commit()
                if active_job.status == TrainingJobStatus.PENDING:
                    dispatch_job_id = active_job.id
                else:
                    return active_job.id

            if not dispatch_job_id:
                self._ensure_recoverable_state(loop=loop, latest_round=latest_round)
                failed_job = await self._find_failed_round_job(
                    session=session,
                    loop=loop,
                    latest_round=latest_round,
                )
                if failed_job is None:
                    raise BadRequestAppException("latest round has no failed job to recover")

                plugin_id, query_strategy, params, resources = self._resolve_recover_job_config(
                    failed_job=failed_job,
                    mode=mode,
                    overrides=overrides,
                )
                recovered_job = self._build_recovered_job(
                    failed_job=failed_job,
                    latest_round=latest_round,
                    plugin_id=plugin_id,
                    query_strategy=query_strategy,
                    params=params,
                    resources=resources,
                )
                session.add(recovered_job)
                await session.flush()
                await session.refresh(recovered_job)

                self._mark_recovered_round_and_loop(
                    loop=loop,
                    round_obj=latest_round,
                    job_id=recovered_job.id,
                    start_now=True,
                )
                session.add(latest_round)
                session.add(loop)

                await session.commit()
                dispatch_job_id = recovered_job.id

        if dispatch_job_id:
            await self._dispatch_job(dispatch_job_id)
            return dispatch_job_id
        raise BadRequestAppException("recover failed: no dispatchable job")

    async def _latest_round(self, session, loop_id: uuid.UUID) -> LoopRound | None:
        rows = await session.exec(
            select(LoopRound)
            .where(LoopRound.loop_id == loop_id)
            .order_by(LoopRound.round_index.desc(), LoopRound.created_at.desc())
            .limit(1)
        )
        return rows.first()

    async def _dispatch_job(self, job_id: uuid.UUID) -> None:
        async with self._session_local() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            logger.info("开始派发轮次任务 loop_id={} job_id={} round_index={}", job.loop_id, job.id, job.round_index)
            assigned = await runtime_dispatcher.assign_job(job)
            if not assigned:
                logger.warning("轮次任务未即时派发成功，转入统一派发队列 job_id={}", job.id)
                await runtime_dispatcher.dispatch_pending_jobs()
            else:
                logger.info(
                    "轮次任务派发成功 request_id={} job_id={} executor_id={}",
                    assigned.request_id,
                    job.id,
                    assigned.executor_id,
                )

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

        loop_config = normalize_loop_global_config(loop.global_config)
        params = dict(loop_config)
        params.pop("job_resources_default", None)
        params.pop("selection", None)
        params.setdefault("topk", loop.query_batch_size)
        params.setdefault("split_seed", round_split_seed(loop.id, round_index))

        warm_start = to_bool(loop_config.get("warm_start"), True)
        params["warm_start"] = warm_start

        resources = dict(loop_config.get("job_resources_default") or {})

        if warm_start and loop.latest_model_id:
            parent_model = await session.get(Model, loop.latest_model_id)
            if parent_model and parent_model.weights_path:
                warm_start_uri = str(parent_model.weights_path)
                presigned = self._build_presigned_download_url(warm_start_uri)
                if warm_start_uri.startswith("s3://") and not presigned:
                    logger.warning(
                        "跳过 warm-start：缺少预签名下载地址 loop_id={} round_index={}",
                        loop.id,
                        round_index,
                    )
                else:
                    params.setdefault("parent_model_id", str(parent_model.id))
                    params.setdefault("base_model", warm_start_uri)
                    if presigned:
                        params.setdefault("base_model_download_url", presigned)

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
            resources=resources,
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
        logger.info(
            "已创建轮次训练任务 loop_id={} round_index={} job_id={} source_commit_id={}",
            loop.id,
            round_index,
            job.id,
            source_commit_id,
        )
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
        if job.status not in {TrainingJobStatus.SUCCESS, TrainingJobStatus.PARTIAL_FAILED}:
            round_obj.status = LoopRoundStatus.FAILED
            round_obj.ended_at = datetime.now(UTC)
            loop.status = ALLoopStatus.FAILED
            loop.last_error = job.last_error or f"job failed: {job.status}"
            session.add(round_obj)
            session.add(loop)
            return None

        batch = await self._create_annotation_batch(session=session, loop=loop, job=job)
        round_metrics = dict(job.metrics or {})
        parent_model_id = str((job.params or {}).get("parent_model_id") or "")
        if parent_model_id:
            round_metrics.setdefault("parent_model_id", parent_model_id)

        if batch is None:
            round_metrics.setdefault("no_candidates", 1.0)
            round_obj.metrics = round_metrics
            round_obj.selected_count = 0
            round_obj.status = LoopRoundStatus.COMPLETED_NO_CANDIDATES
            round_obj.ended_at = datetime.now(UTC)
            session.add(round_obj)

            loop.status = ALLoopStatus.COMPLETED
            loop.is_active = False
            loop.last_error = "no_candidates"
            session.add(loop)
            return None

        round_obj.annotation_batch_id = batch.id
        round_obj.metrics = round_metrics
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

    async def _create_annotation_batch(self, *, session, loop: ALLoop, job: Job) -> AnnotationBatch | None:
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
        loop_config = normalize_loop_global_config(loop.global_config)
        selection = loop_config.get("selection") if isinstance(loop_config.get("selection"), dict) else {}
        min_candidates_required = max(1, to_int(selection.get("min_candidates_required"), 1))
        if len(candidates) < min_candidates_required:
            logger.info(
                "跳过标注批次创建：候选样本不足 job_id={} candidates={} min_candidates_required={}",
                job.id,
                len(candidates),
                min_candidates_required,
            )
            return None

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
        await refresh_batch_progress_by_commit(
            session=session,
            batch=batch,
            commit_id=commit_id,
        )

    async def _should_early_stop(self, *, session, loop: ALLoop) -> bool:
        rounds_rows = await session.exec(
            select(LoopRound)
            .where(
                LoopRound.loop_id == loop.id,
                LoopRound.status.in_(
                    [
                        LoopRoundStatus.COMPLETED,
                        LoopRoundStatus.COMPLETED_NO_CANDIDATES,
                    ]
                ),
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
            parent_model_id=loop.latest_model_id,
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

    def _build_presigned_download_url(self, uri: str) -> str:
        if not uri.startswith("s3://"):
            return ""
        bucket_and_path = uri[5:]
        bucket, _, object_name = bucket_and_path.partition("/")
        if not object_name:
            return ""
        if bucket and bucket != settings.MINIO_BUCKET_NAME:
            logger.warning(
                "跳过 warm-start 预签名地址生成：桶名不匹配 bucket={} expected={}",
                bucket,
                settings.MINIO_BUCKET_NAME,
            )
            return ""
        try:
            return self.storage.get_presigned_url(object_name)
        except Exception:
            logger.exception("生成 warm-start 预签名地址失败 uri={}", uri)
            return ""


loop_orchestrator = LoopOrchestrator()
