"""Runtime round aggregation use-cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from saki_api.modules.runtime.api.round_step import RoundUpdate
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.state_machine import TERMINAL_ROUND_STATES, summarize_step_states
from saki_api.modules.shared.modeling.enums import RoundStatus


def _step_type_text(step: Step) -> str:
    raw = step.step_type.value if hasattr(step.step_type, "value") else step.step_type
    return str(raw or "").strip().lower()


def build_round_update_from_steps(*, round_row: Round, steps: Iterable[Step]) -> RoundUpdate:
    step_rows = list(steps)
    if not step_rows:
        return RoundUpdate(
            state=RoundStatus.PENDING,
            step_counts={},
            final_metrics={},
            final_artifacts={},
        )
    ordered_steps = sorted(
        step_rows,
        key=lambda step: (int(step.step_index or 0), str(step.created_at or "")),
    )

    snapshot = summarize_step_states(step.state for step in ordered_steps)
    round_state = snapshot.state

    payload = RoundUpdate(
        state=round_state,
        step_counts=snapshot.step_counts,
    )

    if round_state == RoundStatus.RUNNING and not round_row.started_at:
        payload.started_at = datetime.now(UTC)
    if round_state in TERMINAL_ROUND_STATES and not round_row.ended_at:
        payload.ended_at = datetime.now(UTC)

    last_step = ordered_steps[-1]
    # final_metrics / final_artifacts are resolved by task-source aggregation pipeline.
    payload.final_metrics = {}
    payload.final_artifacts = {}
    if last_step.last_error:
        payload.terminal_reason = last_step.last_error
    return payload


def apply_round_update(round_row: Round, update: RoundUpdate) -> None:
    payload = update.model_dump(exclude_none=True)
    for key, value in payload.items():
        setattr(round_row, key, value)
