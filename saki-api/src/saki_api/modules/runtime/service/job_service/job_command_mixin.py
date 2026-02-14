"""Job/task command mixin for runtime job service."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.runtime.api.job import JobCreate, JobCreateRequest, JobTaskCreate, JobTaskUpdate, JobUpdate, LoopPatch
from saki_api.modules.runtime.domain import step_specs_for_mode
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus, StepType


class JobCommandMixin:
    @transactional
    async def create_job_for_loop(self, loop_id: uuid.UUID, payload: JobCreateRequest) -> Round:
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
            state=RoundStatus.PENDING,
            step_counts={},
            input_commit_id=payload.input_commit_id,
            round_type=payload.round_type,
            plugin_id=payload.plugin_id,
            query_strategy=payload.query_strategy,
            resolved_params=payload.resolved_params,
            resources=payload.resources,
            strategy_params=payload.strategy_params,
            final_metrics={},
            final_artifacts={},
        )
        return await self.create(create_schema)

    def _build_job_params(self, *, loop: Loop, round_index: int) -> dict[str, Any]:
        params = dict(self._extract_model_request_config(loop.global_config or {}))
        params["round_index"] = round_index
        params["loop_mode"] = loop.mode.value
        params["query_strategy"] = loop.query_strategy
        return params

    @transactional
    async def create_next_job_with_tasks(self, *, loop: Loop, branch: Branch) -> tuple[Round, list[Step]]:
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
                state=RoundStatus.PENDING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                query_strategy=loop.query_strategy,
                resolved_params=params,
                resources=dict((loop.global_config or {}).get("job_resources_default") or {}),
                input_commit_id=source_commit_id,
                final_metrics={},
                final_artifacts={},
            )
        )

        created_tasks: list[Step] = []
        previous_task_id: uuid.UUID | None = None
        for index, task_type in enumerate(step_specs_for_mode(loop.mode), start=1):
            depends_on = [str(previous_task_id)] if previous_task_id else []
            task = await self.job_task_repo.create(
                JobTaskCreate(
                    round_id=job.id,
                    step_type=task_type,
                    state=StepStatus.PENDING,
                    round_index=next_round,
                    step_index=index,
                    depends_on_step_ids=depends_on,
                    resolved_params=params,
                    metrics={},
                    artifacts={},
                    input_commit_id=source_commit_id,
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
                last_round_id=job.id,
                terminal_reason=None,
            ).model_dump(exclude_none=True),
        )
        return job, created_tasks

    @transactional
    async def mark_job_cancelled(self, job_id: uuid.UUID, reason: str | None = None) -> Round:
        job = await self.repository.get_by_id(job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")

        job = await self.repository.update_or_raise(
            job_id,
            JobUpdate(state=RoundStatus.CANCELLED, terminal_reason=reason).model_dump(exclude_none=True),
        )

        tasks = await self.job_task_repo.list_active_by_round(job_id)
        for task in tasks:
            await self.job_task_repo.update_or_raise(
                task.id,
                JobTaskUpdate(state=StepStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
            )
        return job

    async def get_task_by_id_or_raise(self, task_id: uuid.UUID) -> Step:
        return await self.job_task_repo.get_by_id_or_raise(task_id)

    @transactional
    async def mark_task_cancelled(self, task_id: uuid.UUID, reason: str | None = None) -> Step:
        task = await self.job_task_repo.get_by_id(task_id)
        if not task:
            raise NotFoundAppException(f"Task {task_id} not found")
        if task.state in {
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.CANCELLED,
            StepStatus.SKIPPED,
        }:
            return task

        return await self.job_task_repo.update_or_raise(
            task_id,
            JobTaskUpdate(state=StepStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
        )

    @transactional
    async def cleanup_round_predictions(self, *, loop_id: uuid.UUID, round_index: int) -> dict[str, int]:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if round_index <= 0:
            raise BadRequestAppException("round_index must be >= 1")

        jobs = await self.repository.list_by_loop(loop_id)
        target_job = next((item for item in jobs if int(item.round_index) == int(round_index)), None)
        if target_job is None:
            raise NotFoundAppException(f"Round {round_index} not found in loop {loop_id}")

        tasks = await self.job_task_repo.list_by_round(target_job.id)
        score_tasks = [task for task in tasks if task.step_type == StepType.SCORE]

        event_types = ["metric", "progress", "log"]
        deleted_candidates = 0
        deleted_events = 0
        deleted_metrics = 0
        for task in score_tasks:
            deleted_candidates += await self.task_candidate_repo.delete_by_step(task.id)
            deleted_events += await self.task_event_repo.delete_by_step_and_types(step_id=task.id, event_types=event_types)
            deleted_metrics += await self.task_metric_repo.delete_by_step(task.id)

        return {
            "score_steps": len(score_tasks),
            "candidate_rows_deleted": deleted_candidates,
            "event_rows_deleted": deleted_events,
            "metric_rows_deleted": deleted_metrics,
        }
