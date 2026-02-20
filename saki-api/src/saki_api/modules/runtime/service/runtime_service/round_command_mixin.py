"""Round/step command mixin for runtime service."""

from __future__ import annotations

import uuid

from saki_api.modules.access.domain.rbac import AuditAction
from saki_api.modules.access.service.audit import log_audit
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.api.round_step import RoundCreate, RoundCreateRequest, LoopPatch
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.shared.modeling.enums import RoundStatus, StepType


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

    async def get_step_by_id_or_raise(self, step_id: uuid.UUID) -> Step:
        return await self.step_repo.get_by_id_or_raise(step_id)

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
