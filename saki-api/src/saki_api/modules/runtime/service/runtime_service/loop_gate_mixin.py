"""Loop gate decision mixin."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException, ConflictAppException
from saki_api.modules.shared.modeling.enums import (
    LoopGate,
    LoopLifecycle,
    LoopMode,
    LoopPhase,
    RoundStatus,
    RuntimeTaskStatus,
)


class LoopGateMixin:
    async def _compute_loop_gate(
        self,
        loop_id: uuid.UUID,
        *,
        preloaded_loop: Any | None = None,
        preloaded_latest_round: Any | None = None,
    ) -> tuple[LoopGate, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
        loop = preloaded_loop if preloaded_loop is not None else await self.loop_repo.get_by_id_or_raise(loop_id)
        latest_round_cache = preloaded_latest_round
        latest_round_loaded = preloaded_latest_round is not None

        async def _latest_round():
            nonlocal latest_round_cache, latest_round_loaded
            if not latest_round_loaded:
                latest_round_cache = await self.repository.get_latest_by_loop(loop_id)
                latest_round_loaded = True
            return latest_round_cache

        read_action = self._action("read", label="Read", runnable=False)
        observe_action = self._action("observe", label="Observe", runnable=False)
        start_action = self._action("start", label="Start")
        lifecycle_text = str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
        phase_text = str(loop.phase.value if hasattr(loop.phase, "value") else loop.phase).strip().lower()

        if loop.lifecycle == LoopLifecycle.FAILED:
            latest_round = await _latest_round()
            latest_round_state = (
                str(latest_round.state.value if hasattr(latest_round.state, "value") else latest_round.state).strip().lower()
                if latest_round
                else ""
            )
            if latest_round and latest_round_state == RoundStatus.FAILED.value:
                steps = await self.step_repo.list_by_round(latest_round.id)
                task_ids = [step.task_id for step in steps if step.task_id is not None]
                tasks = await self.task_repo.get_by_ids(task_ids) if task_ids else []
                task_status_by_id = {
                    task.id: str(task.status.value if hasattr(task.status, "value") else task.status).strip().lower()
                    for task in tasks
                }
                terminal_task_statuses = {
                    RuntimeTaskStatus.SUCCEEDED.value,
                    RuntimeTaskStatus.FAILED.value,
                    RuntimeTaskStatus.CANCELLED.value,
                    RuntimeTaskStatus.SKIPPED.value,
                }
                has_inflight_tasks = any(
                    step.task_id is None
                    or str(task_status_by_id.get(step.task_id) or "").strip().lower() not in terminal_task_statuses
                    for step in steps
                )
                if not has_inflight_tasks:
                    retry_action = self._action(
                        "retry_round",
                        label="Retry Round",
                        payload={
                            "round_id": str(latest_round.id),
                            "round_index": int(latest_round.round_index),
                            "attempt_index": int(latest_round.attempt_index),
                        },
                    )
                    gate_meta = {
                        "reason": "latest_round_failed",
                        "retry_round_id": str(latest_round.id),
                        "retry_round_index": int(latest_round.round_index),
                        "retry_attempt_index": int(latest_round.attempt_index),
                        "retry_reason_hint": str(latest_round.terminal_reason or ""),
                    }
                    return LoopGate.CAN_RETRY, gate_meta, retry_action, [retry_action, read_action]
            return LoopGate.FAILED, {"reason": "terminal"}, None, [read_action]

        if loop.lifecycle == LoopLifecycle.COMPLETED:
            return LoopGate.COMPLETED, {"reason": "terminal"}, None, [read_action]
        if loop.lifecycle == LoopLifecycle.STOPPED:
            return LoopGate.STOPPED, {"reason": "terminal"}, None, [read_action]

        if loop.lifecycle == LoopLifecycle.PAUSED:
            return LoopGate.PAUSED, {"phase": phase_text}, None, [observe_action]
        if loop.lifecycle == LoopLifecycle.STOPPING:
            return LoopGate.STOPPING, {"phase": phase_text}, None, [observe_action]

        if loop.lifecycle == LoopLifecycle.RUNNING:
            if loop.mode == LoopMode.MANUAL:
                if phase_text != LoopPhase.MANUAL_EVAL.value:
                    return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

                latest_round = await _latest_round()
                if latest_round and latest_round.state == RoundStatus.COMPLETED:
                    round_index = int(latest_round.round_index or 0)
                    if round_index < int(loop.max_rounds or 1):
                        start_next_round_action = self._action("start_next_round", label="Start Next Round")
                        return (
                            LoopGate.CAN_NEXT_ROUND,
                            {
                                "round_index": round_index,
                                "attempt_index": int(latest_round.attempt_index or 1),
                            },
                            start_next_round_action,
                            [start_next_round_action],
                        )
                return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

            if loop.mode == LoopMode.SIMULATION:
                return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

            if phase_text != LoopPhase.AL_WAIT_USER.value:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]

            latest_round = await _latest_round()
            if latest_round is None:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]
            if latest_round.state != RoundStatus.COMPLETED:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]

            configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
            if latest_round.confirmed_at is not None:
                start_next_round_action = self._action("start_next_round", label="Start Next Round")
                confirmed_selected_count = int(latest_round.confirmed_selected_count or 0)
                confirmed_revealed_count = int(latest_round.confirmed_revealed_count or 0)
                confirmed_effective_min_required = int(
                    latest_round.confirmed_effective_min_required
                    or self._effective_round_min_required(
                        selected_count=confirmed_selected_count,
                        configured_min_required=configured_min_required,
                    )
                )
                gate_meta = self._build_wait_user_gate_meta(
                    loop_id=loop_id,
                    round_row=latest_round,
                    selected_count=confirmed_selected_count,
                    revealed_count=confirmed_revealed_count,
                    missing_count=max(0, confirmed_selected_count - confirmed_revealed_count),
                    min_required=confirmed_effective_min_required,
                    configured_min_required=configured_min_required,
                )
                gate_meta.update(
                    {
                        "attempt_index": int(latest_round.attempt_index or 1),
                        "confirmed_at": latest_round.confirmed_at.isoformat() if latest_round.confirmed_at else None,
                        "confirmed_revealed_count": confirmed_revealed_count,
                        "confirmed_selected_count": confirmed_selected_count,
                        "confirmed_effective_min_required": confirmed_effective_min_required,
                    }
                )
                return (
                    LoopGate.CAN_NEXT_ROUND,
                    gate_meta,
                    start_next_round_action,
                    [start_next_round_action],
                )

            probe = await self._probe_round_reveal(loop_id=loop_id, round_id=latest_round.id, loop=loop)
            effective_min_required = self._effective_round_min_required(
                selected_count=probe.selected_count,
                configured_min_required=configured_min_required,
            )
            gate_meta = self._build_wait_user_gate_meta(
                loop_id=loop_id,
                round_row=latest_round,
                selected_count=probe.selected_count,
                revealed_count=probe.revealable_count,
                missing_count=probe.missing_count,
                min_required=effective_min_required,
                configured_min_required=configured_min_required,
            )
            if effective_min_required <= 0 or probe.revealable_count >= effective_min_required:
                confirm_action = self._action("confirm", label="Confirm Reveal")
                selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
                return (
                    LoopGate.CAN_CONFIRM,
                    gate_meta,
                    confirm_action,
                    [confirm_action, selection_adjust_action],
                )
            annotate_action = self._action("annotate", label="Annotate Query Samples")
            selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
            return (
                LoopGate.NEED_ROUND_LABELS,
                gate_meta,
                annotate_action,
                [annotate_action, selection_adjust_action],
            )

        if loop.lifecycle == LoopLifecycle.DRAFT:
            if loop.mode in {LoopMode.MANUAL, LoopMode.SIMULATION}:
                return LoopGate.CAN_START, {"mode": str(loop.mode)}, start_action, [start_action]
            if not loop.active_snapshot_version_id:
                snapshot_action = self._action("snapshot_init", label="Init Snapshot")
                return LoopGate.NEED_SNAPSHOT, {"missing": "snapshot"}, snapshot_action, [snapshot_action, read_action]
            return LoopGate.CAN_START, {"mode": str(loop.mode)}, start_action, [start_action]

        return LoopGate.CAN_START, {"phase": phase_text}, start_action, [start_action]

    async def get_loop_gate(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        latest_round = await self.repository.get_latest_by_loop(loop_id)
        gate, gate_meta, primary_action, gate_actions = await self._compute_loop_gate(
            loop_id,
            preloaded_loop=loop,
            preloaded_latest_round=latest_round,
        )
        actions = self._merge_gate_actions(loop=loop, gate=gate, actions=gate_actions)
        branch_head_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        token_payload = self._decision_token_payload(
            loop=loop,
            gate=gate,
            gate_meta=gate_meta,
            actions=actions,
            latest_round=latest_round,
            branch_head_commit_id=branch_head_commit_id,
        )
        decision_token = self._make_decision_token(token_payload)
        blocking_reasons = self._build_blocking_reasons(
            gate=gate,
            gate_meta=gate_meta,
            primary_action=primary_action,
        )
        return {
            "loop_id": loop.id,
            "phase": loop.phase,
            "lifecycle": loop.lifecycle,
            "gate": gate,
            "gate_meta": gate_meta,
            "primary_action": primary_action,
            "actions": actions,
            "decision_token": decision_token,
            "blocking_reasons": blocking_reasons,
        }

    async def resolve_loop_action_request(
        self,
        *,
        loop_id: uuid.UUID,
        requested_action: str | None,
        decision_token: str | None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        decision = await self.get_loop_gate(loop_id=loop_id)
        latest_token = str(decision.get("decision_token") or "")
        if decision_token and latest_token and str(decision_token) != latest_token:
            raise ConflictAppException(
                message="decision token is stale",
                data={"expected": latest_token, "provided": str(decision_token)},
            )

        action_key = str(requested_action or "").strip().lower()
        if not action_key:
            primary_action = decision.get("primary_action")
            action_key = str((primary_action or {}).get("key") or "").strip().lower()
        if not action_key:
            raise BadRequestAppException("no actionable transition for current gate")

        actions = decision.get("actions") or []
        matched = None
        for item in actions:
            key = str((item or {}).get("key") or "").strip().lower()
            if key == action_key:
                matched = item
                break
        if matched is None:
            raise BadRequestAppException(f"action not allowed in current gate: {action_key}")
        if not bool(matched.get("runnable", True)):
            raise BadRequestAppException(f"action is not runnable in current gate: {action_key}")
        return decision, action_key, matched
