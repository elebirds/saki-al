"""Runtime round aggregation use-cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from saki_api.modules.runtime.api.round_step import RoundUpdate
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.state_machine import TERMINAL_ROUND_STATES, summarize_step_states
from saki_api.modules.shared.modeling.enums import RoundStatus


def build_round_update_from_steps(*, round_row: Round, steps: Iterable[Step]) -> RoundUpdate:
    step_rows = list(steps)
    if not step_rows:
        return RoundUpdate(
            state=RoundStatus.PENDING,
            step_counts={},
            final_metrics={},
            final_artifacts={},
        )

    snapshot = summarize_step_states(step.state for step in step_rows)
    round_state = snapshot.state

    payload = RoundUpdate(
        state=round_state,
        step_counts=snapshot.step_counts,
    )

    if round_state == RoundStatus.RUNNING and not round_row.started_at:
        payload.started_at = datetime.now(UTC)
    if round_state in TERMINAL_ROUND_STATES and not round_row.ended_at:
        payload.ended_at = datetime.now(UTC)

    last_step = step_rows[-1]
    payload.final_metrics = dict(last_step.metrics or {})
    payload.final_artifacts = dict(last_step.artifacts or {})
    if last_step.output_commit_id:
        payload.output_commit_id = last_step.output_commit_id
    if last_step.last_error:
        payload.terminal_reason = last_step.last_error
    return payload


def apply_round_update(round_row: Round, update: RoundUpdate) -> None:
    payload = update.model_dump(exclude_none=True)
    for key, value in payload.items():
        setattr(round_row, key, value)
