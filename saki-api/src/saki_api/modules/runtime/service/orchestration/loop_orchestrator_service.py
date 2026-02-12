"""Background orchestrator for Loop/Job/Task runtime."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from loguru import logger

from saki_api.core.config import settings
from saki_api.infra.db.session import SessionLocal
from saki_api.infra.grpc.dispatcher import runtime_dispatcher
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.runtime.api.job import LoopPatch, LoopSimulationConfig
from saki_api.modules.runtime.domain import (
    DEFAULT_MODE_POLICIES,
    RUNNING_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
)
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.repo.job import JobRepository
from saki_api.modules.runtime.repo.job_task import JobTaskRepository
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.service.application.job_aggregation import build_job_update_from_tasks
from saki_api.modules.runtime.service.job import JobService
from saki_api.modules.shared.modeling.enums import (
    ALLoopMode,
    ALLoopStatus,
    JobStatusV2,
    JobTaskStatus,
)


@dataclass(slots=True)
class RuntimeRepoContext:
    loop: LoopRepository
    project: ProjectReadGateway
    job: JobRepository
    task: JobTaskRepository


class LoopOrchestrator:
    def __init__(self, interval_sec: int | None = None, session_local=SessionLocal) -> None:
        self.interval_sec = max(2, int(interval_sec or settings.RUNTIME_DISPATCH_INTERVAL_SEC))
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._session_local = session_local
        self._mode_policies = DEFAULT_MODE_POLICIES

    @staticmethod
    def _build_repo_context(session) -> RuntimeRepoContext:
        return RuntimeRepoContext(
            loop=LoopRepository(session),
            project=ProjectReadGateway(session),
            job=JobRepository(session),
            task=JobTaskRepository(session),
        )

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
            ctx = self._build_repo_context(session)
            loop_ids = await ctx.loop.list_running_ids()

        for loop_id in loop_ids:
            await self._process_loop(loop_id)

        await runtime_dispatcher.dispatch_pending_tasks()

    async def _process_loop(self, loop_id: uuid.UUID) -> None:
        dispatch_task_ids: list[uuid.UUID] = []
        async with self._session_local() as session:
            ctx = self._build_repo_context(session)

            loop = await ctx.loop.get_by_id(loop_id)
            if not loop or loop.status != ALLoopStatus.RUNNING:
                return

            branch = await ctx.project.get_branch(loop.branch_id)
            if not branch:
                await ctx.loop.update_or_raise(
                    loop.id,
                    LoopPatch(
                        status=ALLoopStatus.FAILED,
                        last_error=f"branch {loop.branch_id} not found",
                    ).model_dump(exclude_none=True),
                )
                await session.commit()
                return

            latest_job = await ctx.job.get_latest_by_loop(loop.id)
            if latest_job is None:
                await self._create_next_job(
                    session=session,
                    loop=loop,
                    branch=branch,
                )
                await session.commit()
                return

            latest_job = await self._refresh_job_aggregate_status(
                task_repo=ctx.task,
                job_repo=ctx.job,
                job=latest_job,
            )

            if latest_job.summary_status in RUNNING_JOB_STATUSES:
                pending = await self._pending_dispatch_tasks(task_repo=ctx.task, job_id=latest_job.id)
                dispatch_task_ids.extend([item.id for item in pending])
                await session.commit()
            elif latest_job.summary_status in TERMINAL_JOB_STATUSES:
                if latest_job.summary_status in {JobStatusV2.JOB_FAILED, JobStatusV2.JOB_CANCELLED}:
                    await ctx.loop.update_or_raise(
                        loop.id,
                        LoopPatch(
                            status=ALLoopStatus.FAILED,
                            last_error=latest_job.last_error,
                        ).model_dump(exclude_none=True),
                    )
                    await session.commit()
                    return

                sim_finished = await self._simulation_finished(loop) if loop.mode == ALLoopMode.SIMULATION else False
                policy = self._mode_policies.get(loop.mode, self._mode_policies[ALLoopMode.ACTIVE_LEARNING])
                decision = policy.on_terminal(loop=loop, sim_finished=sim_finished)

                if decision.set_status is not None:
                    loop.status = decision.set_status
                if decision.set_phase is not None:
                    loop.phase = decision.set_phase
                if decision.set_last_error is not None:
                    loop.last_error = decision.set_last_error

                if decision.create_next_job and loop.status == ALLoopStatus.RUNNING:
                    await self._create_next_job(
                        session=session,
                        loop=loop,
                        branch=branch,
                    )

                await ctx.loop.update_or_raise(
                    loop.id,
                    LoopPatch(
                        status=loop.status,
                        phase=loop.phase,
                        last_error=loop.last_error,
                        current_iteration=loop.current_iteration,
                        last_job_id=loop.last_job_id,
                        phase_meta=loop.phase_meta,
                    ).model_dump(exclude_none=True),
                )
                await session.commit()

        for task_id in dispatch_task_ids:
            await runtime_dispatcher.assign_task(task_id)

    async def _pending_dispatch_tasks(self, *, task_repo: JobTaskRepository, job_id: uuid.UUID) -> list[JobTask]:
        tasks = await task_repo.list_pending_by_job(job_id)
        ready: list[JobTask] = []
        dependency_ids: list[uuid.UUID] = []
        for task in tasks:
            for dependency_id in task.depends_on:
                try:
                    dependency_ids.append(uuid.UUID(str(dependency_id)))
                except Exception:
                    continue
        dependencies = await task_repo.get_by_ids(dependency_ids)
        dependency_map = {item.id: item for item in dependencies}
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
                dependency = dependency_map.get(dependency_uuid)
                if not dependency or dependency.status != JobTaskStatus.SUCCEEDED:
                    dependencies_ok = False
                    break
            if dependencies_ok:
                ready.append(task)
        return ready

    async def _refresh_job_aggregate_status(
        self,
        *,
        session=None,
        task_repo: JobTaskRepository | None = None,
        job_repo: JobRepository | None = None,
        job: Job,
    ) -> Job:
        if job_repo is None:
            if session is None:
                raise RuntimeError("session or job_repo is required")
            job_repo = JobRepository(session)
        task_repo = task_repo or JobTaskRepository(job_repo.session)
        tasks = await task_repo.list_by_job(job.id)
        payload = build_job_update_from_tasks(job=job, tasks=tasks)
        return await job_repo.update_or_raise(job.id, payload.model_dump(exclude_none=True))

    async def _simulation_finished(self, loop) -> bool:
        simulation_config = LoopSimulationConfig.model_validate(
            (loop.global_config or {}).get("simulation") or {}
        )
        current_ratio = float((loop.phase_meta or {}).get("current_ratio") or 0.0)
        seed_ratio = float(simulation_config.seed_ratio or 0.05)
        step_ratio = float(simulation_config.step_ratio or 0.05)
        max_rounds = int(simulation_config.max_rounds or loop.max_rounds)
        if loop.current_iteration >= max_rounds:
            return True
        return current_ratio >= 1.0 and loop.current_iteration > 0 and step_ratio > 0 and seed_ratio > 0

    async def _create_next_job(
        self,
        *,
        session=None,
        loop,
        branch: Branch,
    ) -> Job:
        if session is None:
            raise RuntimeError("session is required")
        job_service = JobService(session)
        job, created_tasks = await job_service.create_next_job_with_tasks(loop=loop, branch=branch)

        for task in created_tasks:
            if not task.depends_on:
                await runtime_dispatcher.enqueue_task(task.id)

        logger.info(
            "created next job and tasks loop_id={} round={} mode={} job_id={} tasks={}",
            loop.id,
            job.round_index,
            loop.mode.value,
            job.id,
            [item.task_type.value for item in created_tasks],
        )
        return job


loop_orchestrator = LoopOrchestrator()
