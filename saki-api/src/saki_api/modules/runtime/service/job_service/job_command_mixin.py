"""Job/task command mixin for runtime job service."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.runtime.api.job import JobCreate, JobCreateRequest, JobTaskCreate, JobTaskUpdate, JobUpdate, LoopPatch
from saki_api.modules.runtime.domain import task_specs_for_mode
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.domain.loop import ALLoop
from saki_api.modules.shared.modeling.enums import JobStatusV2, JobTaskStatus


class JobCommandMixin:
    @transactional
    async def create_job_for_loop(self, loop_id: uuid.UUID, payload: JobCreateRequest) -> Job:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if loop.project_id != payload.project_id:
            raise BadRequestAppException("Loop project_id and request.project_id mismatch")

        updated_loop = await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(current_iteration=loop.current_iteration + 1).model_dump(exclude_none=True),
        )
        create_schema = JobCreate(
            project_id=payload.project_id,
            loop_id=loop_id,
            round_index=updated_loop.current_iteration,
            mode=payload.mode,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            source_commit_id=payload.source_commit_id,
            job_type=payload.job_type,
            plugin_id=payload.plugin_id,
            query_strategy=payload.query_strategy,
            params=payload.params,
            resources=payload.resources,
            strategy_params=payload.strategy_params,
            final_metrics={},
            final_artifacts={},
        )
        return await self.create(create_schema)

    def _build_job_params(self, *, loop: ALLoop, round_index: int) -> dict[str, Any]:
        params = dict(self._extract_model_request_config(loop.global_config or {}))
        params["round_index"] = round_index
        params["loop_mode"] = loop.mode.value
        params["query_strategy"] = loop.query_strategy
        return params

    @transactional
    async def create_next_job_with_tasks(self, *, loop: ALLoop, branch: Branch) -> tuple[Job, list[JobTask]]:
        next_round = loop.current_iteration + 1
        params = self._build_job_params(loop=loop, round_index=next_round)
        source_commit_id = branch.head_commit_id
        source_commit_id, next_phase, phase_meta = await self._resolve_simulation_round(
            loop=loop,
            next_round=next_round,
            source_commit_id=source_commit_id,
            params=params,
        )

        job = await self.create(
            JobCreate(
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
        )

        created_tasks: list[JobTask] = []
        previous_task_id: uuid.UUID | None = None
        for index, task_type in enumerate(task_specs_for_mode(loop.mode), start=1):
            depends_on = [str(previous_task_id)] if previous_task_id else []
            task = await self.job_task_repo.create(
                JobTaskCreate(
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
                ).model_dump(exclude_none=True)
            )
            previous_task_id = task.id
            created_tasks.append(task)

        await self.loop_repo.update_or_raise(
            loop.id,
            LoopPatch(
                phase=next_phase,
                phase_meta=phase_meta,
                current_iteration=next_round,
                last_job_id=job.id,
                last_error=None,
            ).model_dump(exclude_none=True),
        )
        return job, created_tasks

    @transactional
    async def mark_job_cancelled(self, job_id: uuid.UUID, reason: str | None = None) -> Job:
        job = await self.repository.get_by_id(job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")

        job = await self.repository.update_or_raise(
            job_id,
            JobUpdate(summary_status=JobStatusV2.JOB_CANCELLED, last_error=reason).model_dump(exclude_none=True),
        )

        tasks = await self.job_task_repo.list_active_by_job(job_id)
        for task in tasks:
            await self.job_task_repo.update_or_raise(
                task.id,
                JobTaskUpdate(status=JobTaskStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
            )
        return job

    async def get_task_by_id_or_raise(self, task_id: uuid.UUID) -> JobTask:
        return await self.job_task_repo.get_by_id_or_raise(task_id)

    @transactional
    async def mark_task_cancelled(self, task_id: uuid.UUID, reason: str | None = None) -> JobTask:
        task = await self.job_task_repo.get_by_id(task_id)
        if not task:
            raise NotFoundAppException(f"Task {task_id} not found")
        if task.status in {
            JobTaskStatus.SUCCEEDED,
            JobTaskStatus.FAILED,
            JobTaskStatus.CANCELLED,
            JobTaskStatus.SKIPPED,
        }:
            return task

        return await self.job_task_repo.update_or_raise(
            task_id,
            JobTaskUpdate(status=JobTaskStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
        )
