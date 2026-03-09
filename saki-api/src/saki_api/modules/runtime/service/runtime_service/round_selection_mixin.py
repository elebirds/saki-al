"""Round selection override mixin."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.service.runtime_service.snapshot_policy_mixin import _RoundSelectionContext
from saki_api.modules.shared.modeling.enums import (
    LoopLifecycle,
    LoopMode,
    LoopPhase,
    RoundSelectionOverrideOp,
    RoundStatus,
    StepType,
)


class RoundSelectionMixin:
    async def _resolve_round_selection_context(
        self,
        *,
        round_id: uuid.UUID,
        require_wait_phase: bool,
    ) -> _RoundSelectionContext:
        round_row = await self.repository.get_by_id_or_raise(round_id)
        loop = await self.loop_repo.get_by_id_or_raise(round_row.loop_id)
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("round selection override is only available for active_learning loop")

        if require_wait_phase:
            latest_round = await self.repository.get_latest_by_loop(loop.id)
            if latest_round is None:
                raise BadRequestAppException("loop has no round")
            if latest_round.id != round_row.id:
                raise BadRequestAppException("round selection override only supports latest round attempt")
            if loop.phase != LoopPhase.AL_WAIT_USER:
                raise BadRequestAppException("round selection override requires loop phase al_wait_user")
            if loop.lifecycle not in {
                LoopLifecycle.RUNNING,
                LoopLifecycle.PAUSING,
                LoopLifecycle.PAUSED,
                LoopLifecycle.STOPPING,
            }:
                raise BadRequestAppException("round selection override requires loop in running/pausing/paused/stopping lifecycle")
            if round_row.state != RoundStatus.COMPLETED:
                raise BadRequestAppException("round selection override requires round in completed state")
            if round_row.confirmed_at is not None:
                raise BadRequestAppException("round selection override is locked after round confirm")

        steps = await self.step_repo.list_by_round(round_row.id)
        score_steps = [item for item in steps if item.step_type == StepType.SCORE]
        select_steps = [item for item in steps if item.step_type == StepType.SELECT]
        if not score_steps:
            raise BadRequestAppException("round has no score step")
        if not select_steps:
            raise BadRequestAppException("round has no select step")
        score_step = sorted(score_steps, key=lambda item: int(item.step_index), reverse=True)[0]
        select_step = sorted(select_steps, key=lambda item: int(item.step_index), reverse=True)[0]
        if score_step.task_id is None:
            raise BadRequestAppException("score step missing task binding")

        topk, review_pool_size = self._sampling_limits_from_round(round_row=round_row, fallback_topk=loop.query_batch_size)
        score_pool = await self.task_candidate_repo.list_by_task(score_step.task_id)
        if review_pool_size > 0:
            score_pool = score_pool[:review_pool_size]
        auto_selected = score_pool[:topk]
        return _RoundSelectionContext(
            loop=loop,
            round_row=round_row,
            topk=topk,
            review_pool_size=review_pool_size,
            score_step=score_step,
            select_step=select_step,
            score_pool=score_pool,
            auto_selected=auto_selected,
        )

    @staticmethod
    def _compute_effective_selected_ids(
        *,
        auto_selected_ids: list[uuid.UUID],
        score_pool_ids: list[uuid.UUID],
        include_ids: list[uuid.UUID],
        exclude_ids: set[uuid.UUID],
        topk: int,
    ) -> list[uuid.UUID]:
        result: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()

        for sample_id in auto_selected_ids:
            if sample_id in exclude_ids or sample_id in seen:
                continue
            result.append(sample_id)
            seen.add(sample_id)

        for sample_id in include_ids:
            if sample_id in exclude_ids or sample_id in seen:
                continue
            result.append(sample_id)
            seen.add(sample_id)
            if len(result) >= topk:
                return result[:topk]

        if len(result) < topk:
            for sample_id in score_pool_ids:
                if sample_id in exclude_ids or sample_id in seen:
                    continue
                result.append(sample_id)
                seen.add(sample_id)
                if len(result) >= topk:
                    break
        return result[:topk]

    async def _replace_select_candidates_from_score_pool(
        self,
        *,
        select_task_id: uuid.UUID,
        selected_ids: list[uuid.UUID],
        score_pool_by_id: dict[uuid.UUID, TaskCandidateItem],
    ) -> None:
        await self.task_candidate_repo.delete_by_task(select_task_id)
        rows: list[dict[str, Any]] = []
        for rank, sample_id in enumerate(selected_ids, start=1):
            source = score_pool_by_id.get(sample_id)
            if source is None:
                continue
            rows.append(
                {
                    "task_id": select_task_id,
                    "sample_id": sample_id,
                    "rank": rank,
                    "score": float(source.score or 0.0),
                    "reason": dict(source.reason or {}),
                    "prediction_snapshot": dict(source.prediction_snapshot or {}),
                }
            )
        if rows:
            await self.task_candidate_repo.create_many(rows)

    async def _build_round_selection_payload(
        self,
        *,
        context: _RoundSelectionContext,
    ) -> dict[str, Any]:
        overrides = await self.al_round_selection_override_repo.list_by_round(context.round_row.id)
        include_ids = self._dedupe_uuid_list(
            [item.sample_id for item in overrides if item.op == RoundSelectionOverrideOp.INCLUDE]
        )
        exclude_ids = set(
            self._dedupe_uuid_list([item.sample_id for item in overrides if item.op == RoundSelectionOverrideOp.EXCLUDE])
        )
        score_pool_ids = [item.sample_id for item in context.score_pool]
        effective_ids = self._compute_effective_selected_ids(
            auto_selected_ids=[item.sample_id for item in context.auto_selected],
            score_pool_ids=score_pool_ids,
            include_ids=include_ids,
            exclude_ids=exclude_ids,
            topk=context.topk,
        )
        score_pool_by_id = {item.sample_id: item for item in context.score_pool}

        return {
            "round_id": context.round_row.id,
            "loop_id": context.loop.id,
            "round_index": int(context.round_row.round_index),
            "attempt_index": int(context.round_row.attempt_index),
            "topk": int(context.topk),
            "review_pool_size": int(context.review_pool_size),
            "auto_selected": [
                self._selection_candidate_payload(item, rank=idx + 1) for idx, item in enumerate(context.auto_selected)
            ],
            "score_pool": [self._selection_candidate_payload(item) for item in context.score_pool],
            "overrides": [
                {
                    "sample_id": row.sample_id,
                    "op": row.op,
                    "reason": row.reason,
                }
                for row in overrides
            ],
            "effective_selected": [
                self._selection_candidate_payload(score_pool_by_id[sample_id], rank=idx + 1)
                for idx, sample_id in enumerate(effective_ids)
                if sample_id in score_pool_by_id
            ],
            "selected_count": int(len(effective_ids)),
            "include_count": int(len(include_ids)),
            "exclude_count": int(len(exclude_ids)),
            "_effective_selected_ids": effective_ids,
        }

    async def get_round_selection(self, *, round_id: uuid.UUID) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=False)
        payload = await self._build_round_selection_payload(context=context)
        payload.pop("_effective_selected_ids", None)
        return payload

    @transactional
    async def apply_round_selection_override(
        self,
        *,
        round_id: uuid.UUID,
        include_sample_ids: list[uuid.UUID],
        exclude_sample_ids: list[uuid.UUID],
        actor_user_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=True)
        include_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in include_sample_ids or []])
        exclude_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in exclude_sample_ids or []])
        include_set = set(include_ids)
        exclude_set = set(exclude_ids)
        overlap = include_set & exclude_set
        if overlap:
            raise BadRequestAppException("include_sample_ids and exclude_sample_ids cannot overlap")

        score_pool_ids = {item.sample_id for item in context.score_pool}
        invalid_include = [sample_id for sample_id in include_ids if sample_id not in score_pool_ids]
        if invalid_include:
            preview = ",".join(str(item) for item in invalid_include[:5])
            raise BadRequestAppException(f"include sample is not in score pool: {preview}")

        await self.al_round_selection_override_repo.replace_round_overrides(
            round_id=context.round_row.id,
            include_ids=include_ids,
            exclude_ids=exclude_ids,
            created_by=actor_user_id,
            reason=(str(reason or "").strip() or None),
        )

        payload = await self._build_round_selection_payload(context=context)
        effective_ids = list(payload.get("_effective_selected_ids") or [])
        score_pool_by_id = {item.sample_id: item for item in context.score_pool}
        if context.select_step.task_id is None:
            raise BadRequestAppException("select step missing task binding")
        await self._replace_select_candidates_from_score_pool(
            select_task_id=context.select_step.task_id,
            selected_ids=effective_ids,
            score_pool_by_id=score_pool_by_id,
        )

        payload.pop("_effective_selected_ids", None)
        return payload

    @transactional
    async def reset_round_selection_override(self, *, round_id: uuid.UUID) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=True)
        await self.al_round_selection_override_repo.reset_round(context.round_row.id)
        if context.select_step.task_id is None:
            raise BadRequestAppException("select step missing task binding")
        await self._replace_select_candidates_from_score_pool(
            select_task_id=context.select_step.task_id,
            selected_ids=[item.sample_id for item in context.auto_selected],
            score_pool_by_id={item.sample_id: item for item in context.score_pool},
        )
        payload = await self._build_round_selection_payload(context=context)
        payload.pop("_effective_selected_ids", None)
        return payload
