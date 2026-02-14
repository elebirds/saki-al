"""Runtime loop-mode domain rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase, LoopStatus, StepType

LOOP_STEP_SPECS_BY_MODE: dict[LoopMode, tuple[StepType, ...]] = {
    LoopMode.SIMULATION: (
        StepType.TRAIN,
        StepType.SCORE,
        StepType.EVAL,
        StepType.SELECT,
        StepType.ACTIVATE_SAMPLES,
        StepType.ADVANCE_BRANCH,
    ),
    LoopMode.ACTIVE_LEARNING: (
        StepType.TRAIN,
        StepType.SCORE,
        StepType.EVAL,
        StepType.SELECT,
    ),
    LoopMode.MANUAL: (
        StepType.TRAIN,
        StepType.EVAL,
        StepType.EXPORT,
    ),
}


def step_specs_for_mode(mode: LoopMode) -> tuple[StepType, ...]:
    return LOOP_STEP_SPECS_BY_MODE.get(mode, LOOP_STEP_SPECS_BY_MODE[LoopMode.ACTIVE_LEARNING])


def phase_for_mode(mode: LoopMode) -> LoopPhase:
    if mode == LoopMode.SIMULATION:
        return LoopPhase.SIM_BOOTSTRAP
    if mode == LoopMode.MANUAL:
        return LoopPhase.MANUAL_BOOTSTRAP
    return LoopPhase.AL_BOOTSTRAP


@dataclass(slots=True)
class LoopTerminalDecision:
    set_status: LoopStatus | None = None
    set_phase: LoopPhase | None = None
    set_terminal_reason: str | None = None
    create_next_round: bool = False


class LoopModePolicy(Protocol):
    def on_terminal(self, *, loop, sim_finished: bool, latest_round_index: int) -> LoopTerminalDecision:
        ...


class ActiveLearningModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool, latest_round_index: int) -> LoopTerminalDecision:  # noqa: ARG002
        if latest_round_index >= loop.max_rounds:
            return LoopTerminalDecision(set_status=LoopStatus.COMPLETED, set_phase=LoopPhase.AL_FINALIZE)
        return LoopTerminalDecision(set_phase=LoopPhase.AL_WAIT_USER)


class SimulationModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool, latest_round_index: int) -> LoopTerminalDecision:
        if latest_round_index >= loop.max_rounds or sim_finished:
            return LoopTerminalDecision(set_status=LoopStatus.COMPLETED, set_phase=LoopPhase.SIM_FINALIZE)
        return LoopTerminalDecision(create_next_round=True, set_phase=LoopPhase.SIM_TRAIN)


class ManualModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool, latest_round_index: int) -> LoopTerminalDecision:  # noqa: ARG002
        return LoopTerminalDecision(set_status=LoopStatus.COMPLETED, set_phase=LoopPhase.MANUAL_FINALIZE)


DEFAULT_MODE_POLICIES: dict[LoopMode, LoopModePolicy] = {
    LoopMode.ACTIVE_LEARNING: ActiveLearningModePolicy(),
    LoopMode.SIMULATION: SimulationModePolicy(),
    LoopMode.MANUAL: ManualModePolicy(),
}
