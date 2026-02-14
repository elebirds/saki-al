"""Runtime status-machine domain rules."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus

TERMINAL_STEP_STATES: set[StepStatus] = {
    StepStatus.SUCCEEDED,
    StepStatus.FAILED,
    StepStatus.CANCELLED,
    StepStatus.SKIPPED,
}

RUNNING_STEP_STATES: set[StepStatus] = {
    StepStatus.RUNNING,
    StepStatus.DISPATCHING,
    StepStatus.RETRYING,
}

TERMINAL_ROUND_STATES: set[RoundStatus] = {
    RoundStatus.COMPLETED,
    RoundStatus.FAILED,
    RoundStatus.CANCELLED,
}

RUNNING_ROUND_STATES: set[RoundStatus] = {
    RoundStatus.PENDING,
    RoundStatus.RUNNING,
    RoundStatus.WAIT_USER,
}


@dataclass(slots=True, frozen=True)
class RoundAggregateSnapshot:
    state: RoundStatus
    step_counts: dict[str, int]
    all_terminal: bool
    any_running: bool
    any_failed: bool
    any_cancelled: bool
    all_succeeded: bool


def summarize_step_states(states: Iterable[StepStatus]) -> RoundAggregateSnapshot:
    values = list(states)
    if not values:
        return RoundAggregateSnapshot(
            state=RoundStatus.PENDING,
            step_counts={},
            all_terminal=False,
            any_running=False,
            any_failed=False,
            any_cancelled=False,
            all_succeeded=False,
        )

    counter = Counter(item.value for item in values)
    all_terminal = all(item in TERMINAL_STEP_STATES for item in values)
    any_running = any(item in RUNNING_STEP_STATES for item in values)
    any_failed = any(item == StepStatus.FAILED for item in values)
    any_cancelled = any(item == StepStatus.CANCELLED for item in values)
    all_succeeded = all(item in {StepStatus.SUCCEEDED, StepStatus.SKIPPED} for item in values)

    if any_running:
        state = RoundStatus.RUNNING
    elif all_terminal and all_succeeded:
        state = RoundStatus.COMPLETED
    elif all_terminal and any_cancelled and not any_failed:
        state = RoundStatus.CANCELLED
    elif all_terminal and any_failed:
        state = RoundStatus.FAILED
    else:
        state = RoundStatus.PENDING

    return RoundAggregateSnapshot(
        state=state,
        step_counts=dict(counter),
        all_terminal=all_terminal,
        any_running=any_running,
        any_failed=any_failed,
        any_cancelled=any_cancelled,
        all_succeeded=all_succeeded,
    )
