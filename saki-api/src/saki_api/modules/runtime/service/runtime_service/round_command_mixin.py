"""Round/step command mixin for runtime service."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.modules.access.domain.rbac import AuditAction
from saki_api.modules.access.service.audit import log_audit
from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.runtime.api.round_step import RoundCreate, RoundCreateRequest, StepCreate, StepUpdate, RoundUpdate, LoopPatch
from saki_api.modules.runtime.domain import step_specs_for_mode
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import RoundStatus, StepDispatchKind, StepStatus, StepType


class RoundCommandMixin:
    @transactional
    async def create_round_for_loop(self, loop_id: uuid.UUID, payload: RoundCreateRequest) -> Round:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if loop.project_id != payload.project_id:
            raise BadRequestAppException("Loop project_id and request.project_id mismatch")

        latest_round = await self.repository.get_latest_by_loop(loop_id)
        next_round = (int(latest_round.round_index) if latest_round else 0) + 1

        await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(current_iteration=next_round).model_dump(exclude_none=True),
        )
        create_schema = RoundCreate(
            project_id=payload.project_id,
            loop_id=loop_id,
            round_index=next_round,
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

    def _build_round_params(self, *, loop: Loop, round_index: int) -> dict[str, Any]:
        params = dict(self._extract_model_request_config(loop.global_config or {}))
        params["round_index"] = round_index
        params["loop_mode"] = loop.mode.value
        params["query_strategy"] = loop.query_strategy
        return params

    @transactional
    async def create_next_round_with_steps(self, *, loop: Loop, branch: Branch) -> tuple[Round, list[Step]]:
        latest_round = await self.repository.get_latest_by_loop(loop.id)
        next_round = (int(latest_round.round_index) if latest_round else 0) + 1
        params = self._build_round_params(loop=loop, round_index=next_round)
        source_commit_id = branch.head_commit_id
        source_commit_id, next_phase, phase_meta = await self._resolve_simulation_round(
            loop=loop,
            next_round=next_round,
            source_commit_id=source_commit_id,
            params=params,
        )

        round_item = await self.create(
            RoundCreate(
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
                resources=dict((loop.global_config or {}).get("round_resources_default") or {}),
                input_commit_id=source_commit_id,
                final_metrics={},
                final_artifacts={},
            )
        )

        created_steps: list[Step] = []
        previous_step_id: uuid.UUID | None = None
        for index, step_type in enumerate(step_specs_for_mode(loop.mode), start=1):
            depends_on = [str(previous_step_id)] if previous_step_id else []
            dispatch_kind = (
                StepDispatchKind.ORCHESTRATOR
                if step_type in {StepType.SELECT, StepType.ACTIVATE_SAMPLES, StepType.ADVANCE_BRANCH}
                else StepDispatchKind.DISPATCHABLE
            )
            step = await self.step_repo.create(
                StepCreate(
                    round_id=round_item.id,
                    step_type=step_type,
                    dispatch_kind=dispatch_kind,
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
            previous_step_id = step.id
            created_steps.append(step)

        await self.loop_repo.update_or_raise(
            loop.id,
            LoopPatch(
                phase=next_phase,
                phase_meta=phase_meta,
                current_iteration=next_round,
                terminal_reason=None,
            ).model_dump(exclude_none=True),
        )
        return round_item, created_steps

    @transactional
    async def mark_round_cancelled(self, round_id: uuid.UUID, reason: str | None = None) -> Round:
        round_item = await self.repository.get_by_id(round_id)
        if not round_item:
            raise NotFoundAppException(f"Round {round_id} not found")

        round_item = await self.repository.update_or_raise(
            round_id,
            RoundUpdate(state=RoundStatus.CANCELLED, terminal_reason=reason).model_dump(exclude_none=True),
        )

        steps = await self.step_repo.list_active_by_round(round_id)
        for step in steps:
            await self.step_repo.update_or_raise(
                step.id,
                StepUpdate(state=StepStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
            )
        return round_item

    async def get_step_by_id_or_raise(self, step_id: uuid.UUID) -> Step:
        return await self.step_repo.get_by_id_or_raise(step_id)

    @transactional
    async def mark_step_cancelled(self, step_id: uuid.UUID, reason: str | None = None) -> Step:
        step = await self.step_repo.get_by_id(step_id)
        if not step:
            raise NotFoundAppException(f"Step {step_id} not found")
        if step.state in {
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.CANCELLED,
            StepStatus.SKIPPED,
        }:
            return step

        return await self.step_repo.update_or_raise(
            step_id,
            StepUpdate(state=StepStatus.CANCELLED, last_error=reason).model_dump(exclude_none=True),
        )

    @transactional
    async def cleanup_round_predictions(
        self,
        *,
        loop_id: uuid.UUID,
        round_index: int,
        actor_user_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if round_index <= 0:
            raise BadRequestAppException("round_index must be >= 1")

        rounds = await self.repository.list_by_loop(loop_id)
        target_round = next((item for item in rounds if int(item.round_index) == int(round_index)), None)
        if target_round is None:
            raise NotFoundAppException(f"Round {round_index} not found in loop {loop_id}")

        steps = await self.step_repo.list_by_round(target_round.id)
        score_steps = [step for step in steps if step.step_type == StepType.SCORE]

        event_types = ["metric", "progress", "log"]
        deleted_candidates = 0
        deleted_events = 0
        deleted_metrics = 0
        for step in score_steps:
            deleted_candidates += await self.step_candidate_repo.delete_by_step(step.id)
            deleted_events += await self.step_event_repo.delete_by_step_and_types(step_id=step.id, event_types=event_types)
            deleted_metrics += await self.step_metric_repo.delete_by_step(step.id)

        stats = {
            "score_steps": len(score_steps),
            "candidate_rows_deleted": deleted_candidates,
            "event_rows_deleted": deleted_events,
            "metric_rows_deleted": deleted_metrics,
        }
        await log_audit(
            session=self.session,
            action=AuditAction.PERMISSION_GRANTED,
            target_type="runtime.cleanup_round_predictions",
            target_id=target_round.id,
            new_value={
                "loop_id": str(loop_id),
                "round_id": str(target_round.id),
                "round_index": int(round_index),
                "score_steps": int(stats["score_steps"]),
                "candidate_rows_deleted": int(stats["candidate_rows_deleted"]),
                "event_rows_deleted": int(stats["event_rows_deleted"]),
                "metric_rows_deleted": int(stats["metric_rows_deleted"]),
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
            },
        )
        return stats
