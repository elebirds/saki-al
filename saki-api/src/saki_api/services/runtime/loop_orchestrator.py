"""Background orchestrator for Loop/Job/Task runtime."""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlmodel import func, select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models.enums import (
    ALLoopMode,
    ALLoopStatus,
    JobStatusV2,
    JobTaskStatus,
    JobTaskType,
    LoopPhase,
)
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_task import JobTask


TERMINAL_JOB_STATUS = {
    JobStatusV2.JOB_SUCCEEDED,
    JobStatusV2.JOB_PARTIAL_FAILED,
    JobStatusV2.JOB_FAILED,
    JobStatusV2.JOB_CANCELLED,
}

RUNNING_JOB_STATUS = {JobStatusV2.JOB_PENDING, JobStatusV2.JOB_RUNNING}


class LoopOrchestrator:
    def __init__(self, interval_sec: int | None = None, session_local=SessionLocal) -> None:
        self.interval_sec = max(2, int(interval_sec or settings.RUNTIME_DISPATCH_INTERVAL_SEC))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._session_local = session_local

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="loop-orchestrator")
        logger.info("loop orchestrator started interval_sec={}", self.interval_sec)

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
                logger.exception("loop orchestrator tick failed error={}", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_sec)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        async with self._session_local() as session:
            from saki_api.models.l3.loop import ALLoop

            rows = await session.exec(select(ALLoop.id).where(ALLoop.status == ALLoopStatus.RUNNING))
            loop_ids = list(rows.all())

        for loop_id in loop_ids:
            await self._process_loop(loop_id)

        await runtime_dispatcher.dispatch_pending_tasks()

    async def _process_loop(self, loop_id: uuid.UUID) -> None:
        dispatch_task_ids: list[uuid.UUID] = []
        async with self._session_local() as session:
            from saki_api.models.l3.loop import ALLoop

            loop = await session.get(ALLoop, loop_id)
            if not loop or loop.status != ALLoopStatus.RUNNING:
                return

            branch = await session.get(Branch, loop.branch_id)
            if not branch:
                loop.status = ALLoopStatus.FAILED
                loop.last_error = f"branch {loop.branch_id} not found"
                session.add(loop)
                await session.commit()
                return

            latest_job = await self._latest_job(session, loop.id)
            if latest_job is None:
                await self._create_next_job(session=session, loop=loop, branch=branch)
                await session.commit()
                return

            await self._refresh_job_aggregate_status(session=session, job=latest_job)

            if latest_job.summary_status in RUNNING_JOB_STATUS:
                pending = await self._pending_dispatch_tasks(session=session, job_id=latest_job.id)
                dispatch_task_ids.extend([item.id for item in pending])
                await session.commit()
            elif latest_job.summary_status in TERMINAL_JOB_STATUS:
                if latest_job.summary_status in {JobStatusV2.JOB_FAILED, JobStatusV2.JOB_CANCELLED}:
                    loop.status = ALLoopStatus.FAILED
                    loop.last_error = latest_job.last_error
                    session.add(loop)
                    await session.commit()
                    return

                if loop.mode == ALLoopMode.MANUAL:
                    if loop.phase == LoopPhase.MANUAL_TASK_RUNNING:
                        loop.phase = LoopPhase.MANUAL_WAIT_CONFIRM
                    elif loop.phase == LoopPhase.MANUAL_FINALIZE:
                        if loop.current_iteration >= loop.max_rounds:
                            loop.status = ALLoopStatus.COMPLETED
                        else:
                            await self._create_next_job(session=session, loop=loop, branch=branch)
                    elif loop.phase == LoopPhase.MANUAL_IDLE:
                        await self._create_next_job(session=session, loop=loop, branch=branch)
                    session.add(loop)
                    await session.commit()
                elif loop.mode == ALLoopMode.SIMULATION:
                    if loop.current_iteration >= loop.max_rounds:
                        loop.status = ALLoopStatus.COMPLETED
                        loop.phase = LoopPhase.SIM_EVAL
                        session.add(loop)
                        await session.commit()
                    else:
                        sim_finished = await self._simulation_finished(loop)
                        if sim_finished:
                            loop.status = ALLoopStatus.COMPLETED
                            loop.phase = LoopPhase.SIM_EVAL
                            session.add(loop)
                            await session.commit()
                        else:
                            await self._create_next_job(session=session, loop=loop, branch=branch)
                            await session.commit()
                else:
                    if loop.current_iteration >= loop.max_rounds:
                        loop.status = ALLoopStatus.COMPLETED
                        loop.phase = LoopPhase.AL_EVAL
                        session.add(loop)
                        await session.commit()
                    else:
                        await self._create_next_job(session=session, loop=loop, branch=branch)
                        await session.commit()

        for task_id in dispatch_task_ids:
            await runtime_dispatcher.assign_task(task_id)

    async def _latest_job(self, session, loop_id: uuid.UUID) -> Job | None:
        rows = await session.exec(
            select(Job)
            .where(Job.loop_id == loop_id)
            .order_by(Job.round_index.desc(), Job.created_at.desc())
            .limit(1)
        )
        return rows.first()

    async def _pending_dispatch_tasks(self, session, job_id: uuid.UUID) -> list[JobTask]:
        rows = await session.exec(
            select(JobTask)
            .where(JobTask.job_id == job_id, JobTask.status == JobTaskStatus.PENDING)
            .order_by(JobTask.task_index.asc())
        )
        tasks = list(rows.all())
        ready: list[JobTask] = []
        for task in tasks:
            if not task.depends_on:
                ready.append(task)
                continue
            dependencies_ok = True
            for dependency_id in task.depends_on:
                try:
                    dependency_uuid = uuid.UUID(str(dependency_id))
                except Exception:
                    dependencies_ok = False
                    break
                dependency = await session.get(JobTask, dependency_uuid)
                if not dependency or dependency.status != JobTaskStatus.SUCCEEDED:
                    dependencies_ok = False
                    break
            if dependencies_ok:
                ready.append(task)
        return ready

    async def _refresh_job_aggregate_status(self, *, session, job: Job) -> None:
        rows = await session.exec(
            select(JobTask).where(JobTask.job_id == job.id).order_by(JobTask.task_index.asc())
        )
        tasks = list(rows.all())
        if not tasks:
            job.summary_status = JobStatusV2.JOB_PENDING
            job.task_counts = {}
            session.add(job)
            return

        counts: dict[str, int] = {}
        for task in tasks:
            key = task.status.value
            counts[key] = counts.get(key, 0) + 1

        all_terminal = all(
            task.status
            in {
                JobTaskStatus.SUCCEEDED,
                JobTaskStatus.FAILED,
                JobTaskStatus.CANCELLED,
                JobTaskStatus.SKIPPED,
            }
            for task in tasks
        )
        any_running = any(
            task.status
            in {
                JobTaskStatus.RUNNING,
                JobTaskStatus.DISPATCHING,
                JobTaskStatus.RETRYING,
            }
            for task in tasks
        )
        any_failed = any(task.status == JobTaskStatus.FAILED for task in tasks)
        any_cancelled = any(task.status == JobTaskStatus.CANCELLED for task in tasks)
        all_succeeded = all(task.status in {JobTaskStatus.SUCCEEDED, JobTaskStatus.SKIPPED} for task in tasks)

        if any_running:
            next_status = JobStatusV2.JOB_RUNNING
        elif all_terminal and all_succeeded:
            next_status = JobStatusV2.JOB_SUCCEEDED
        elif all_terminal and any_cancelled and not any_failed:
            next_status = JobStatusV2.JOB_CANCELLED
        elif all_terminal and any_failed and all(task.status == JobTaskStatus.FAILED for task in tasks):
            next_status = JobStatusV2.JOB_FAILED
        elif all_terminal and (any_failed or any_cancelled):
            next_status = JobStatusV2.JOB_PARTIAL_FAILED
        else:
            next_status = JobStatusV2.JOB_PENDING

        job.summary_status = next_status
        job.task_counts = counts
        if next_status == JobStatusV2.JOB_RUNNING and not job.started_at:
            job.started_at = datetime.now(UTC)
        if next_status in TERMINAL_JOB_STATUS and not job.ended_at:
            job.ended_at = datetime.now(UTC)

        if tasks:
            job.final_metrics = dict(tasks[-1].metrics or {})
            job.final_artifacts = dict(tasks[-1].artifacts or {})
            if tasks[-1].result_commit_id:
                job.result_commit_id = tasks[-1].result_commit_id

        session.add(job)

    async def _simulation_finished(self, loop) -> bool:
        simulation_config = dict((loop.global_config or {}).get("simulation") or {})
        current_ratio = float((loop.phase_meta or {}).get("current_ratio") or 0.0)
        seed_ratio = float(simulation_config.get("seed_ratio") or 0.05)
        step_ratio = float(simulation_config.get("step_ratio") or 0.05)
        max_rounds = int(simulation_config.get("max_rounds") or loop.max_rounds)
        if loop.current_iteration >= max_rounds:
            return True
        return current_ratio >= 1.0 and loop.current_iteration > 0 and step_ratio > 0 and seed_ratio > 0

    async def _count_oracle_samples(self, session, oracle_commit_id: uuid.UUID) -> int:
        stmt = select(func.count(func.distinct(CommitAnnotationMap.sample_id))).where(
            CommitAnnotationMap.commit_id == oracle_commit_id,
        )
        value = (await session.exec(stmt)).one()
        return int(value or 0)

    async def _create_next_job(self, *, session, loop, branch: Branch) -> Job:
        from saki_api.models.l3.loop import ALLoop

        loop = loop if isinstance(loop, ALLoop) else await session.get(ALLoop, loop.id)
        if loop is None:
            raise RuntimeError("loop not found while creating next job")

        next_round = loop.current_iteration + 1

        params = dict((loop.global_config or {}).get("model_request_config") or {})
        params["round_index"] = next_round
        params["loop_mode"] = loop.mode.value
        params["query_strategy"] = loop.query_strategy

        source_commit_id = branch.head_commit_id
        if loop.mode == ALLoopMode.SIMULATION:
            simulation = dict((loop.global_config or {}).get("simulation") or {})
            oracle_commit_raw = str(simulation.get("oracle_commit_id") or "").strip()
            if not oracle_commit_raw:
                raise RuntimeError("simulation mode requires oracle_commit_id")
            oracle_commit_id = uuid.UUID(oracle_commit_raw)
            total_count = await self._count_oracle_samples(session, oracle_commit_id)
            if total_count <= 0:
                raise RuntimeError("simulation oracle commit has no labeled samples")

            seed_ratio = float(simulation.get("seed_ratio") or 0.05)
            step_ratio = float(simulation.get("step_ratio") or 0.05)
            target_ratio = min(1.0, seed_ratio + (next_round - 1) * step_ratio)
            prev_ratio = float((loop.phase_meta or {}).get("current_ratio") or 0.0)
            prev_selected = int((loop.phase_meta or {}).get("selected_count") or max(1, math.ceil(seed_ratio * total_count)))
            target_total = max(prev_selected, int(math.ceil(target_ratio * total_count)))
            add_count = max(0, target_total - prev_selected)

            phase_meta = dict(loop.phase_meta or {})
            phase_meta.update(
                {
                    "total_count": total_count,
                    "current_ratio": target_ratio,
                    "selected_count": target_total,
                    "add_count": add_count,
                    "prev_ratio": prev_ratio,
                }
            )
            loop.phase_meta = phase_meta
            params.update(
                {
                    "simulation": {
                        "oracle_commit_id": str(oracle_commit_id),
                        "seed_ratio": seed_ratio,
                        "step_ratio": step_ratio,
                        "target_ratio": target_ratio,
                        "total_count": total_count,
                        "add_count": add_count,
                        "single_seed": simulation.get("single_seed", 0),
                    }
                }
            )
            source_commit_id = oracle_commit_id
            loop.phase = LoopPhase.SIM_TRAIN
        elif loop.mode == ALLoopMode.MANUAL:
            loop.phase = LoopPhase.MANUAL_TASK_RUNNING
        else:
            loop.phase = LoopPhase.AL_TRAIN

        job = Job(
            project_id=loop.project_id,
            loop_id=loop.id,
            round_index=next_round,
            mode=loop.mode,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            job_type="loop_job",
            plugin_id=loop.model_arch,
            query_strategy=loop.query_strategy,
            params=params,
            resources=dict((loop.global_config or {}).get("job_resources_default") or {}),
            source_commit_id=source_commit_id,
            final_metrics={},
            final_artifacts={},
        )
        session.add(job)
        await session.flush()

        task_specs: list[JobTaskType]
        if loop.mode == ALLoopMode.SIMULATION:
            task_specs = [
                JobTaskType.TRAIN,
                JobTaskType.SCORE,
                JobTaskType.AUTO_LABEL,
                JobTaskType.EVAL,
            ]
        else:
            task_specs = [
                JobTaskType.TRAIN,
                JobTaskType.SCORE,
                JobTaskType.SELECT,
                JobTaskType.UPLOAD_ARTIFACT,
            ]

        previous_task_id: uuid.UUID | None = None
        created_tasks: list[JobTask] = []
        for index, task_type in enumerate(task_specs, start=1):
            depends_on = [str(previous_task_id)] if previous_task_id else []
            task = JobTask(
                job_id=job.id,
                task_type=task_type,
                status=JobTaskStatus.PENDING,
                round_index=next_round,
                task_index=index,
                depends_on=depends_on,
                params=params,
                metrics={},
                artifacts={},
                source_commit_id=source_commit_id,
                attempt=1,
                max_attempts=max(1, int(settings.RUNTIME_MAX_RETRY_COUNT) + 1),
            )
            session.add(task)
            await session.flush()
            previous_task_id = task.id
            created_tasks.append(task)

        loop.current_iteration = next_round
        loop.last_job_id = job.id
        loop.last_error = None
        session.add(loop)

        for task in created_tasks:
            if not task.depends_on:
                await runtime_dispatcher.enqueue_task(task.id)

        logger.info(
            "created next job and tasks loop_id={} round={} mode={} job_id={} tasks={}",
            loop.id,
            next_round,
            loop.mode.value,
            job.id,
            [item.task_type.value for item in created_tasks],
        )
        return job


loop_orchestrator = LoopOrchestrator()
