"""Round/step command mixin for runtime service."""

from __future__ import annotations

import uuid

from saki_api.modules.access.domain.rbac import AuditAction
from saki_api.modules.access.service.audit import log_audit
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.shared.modeling.enums import StepType


class RoundCommandMixin:
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
            if step.task_id is None:
                continue
            deleted_candidates += await self.task_candidate_repo.delete_by_task(step.task_id)
            deleted_events += await self.task_event_repo.delete_by_task_and_types(
                task_id=step.task_id,
                event_types=event_types,
            )
            deleted_metrics += await self.task_metric_repo.delete_by_task(step.task_id)

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
