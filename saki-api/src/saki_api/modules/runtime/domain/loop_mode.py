"""Runtime loop-mode domain rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from saki_api.modules.shared.modeling.enums import ALLoopMode, ALLoopStatus, JobTaskType, LoopPhase

LOOP_TASK_SPECS_BY_MODE: dict[ALLoopMode, tuple[JobTaskType, ...]] = {
    ALLoopMode.SIMULATION: (
        JobTaskType.TRAIN,
        JobTaskType.SCORE,
        JobTaskType.AUTO_LABEL,
        JobTaskType.EVAL,
    ),
    ALLoopMode.ACTIVE_LEARNING: (
        JobTaskType.TRAIN,
        JobTaskType.SCORE,
        JobTaskType.SELECT,
        JobTaskType.UPLOAD_ARTIFACT,
    ),
    ALLoopMode.MANUAL: (
        JobTaskType.TRAIN,
        JobTaskType.SCORE,
        JobTaskType.SELECT,
        JobTaskType.UPLOAD_ARTIFACT,
    ),
}


def task_specs_for_mode(mode: ALLoopMode) -> tuple[JobTaskType, ...]:
    return LOOP_TASK_SPECS_BY_MODE.get(mode, LOOP_TASK_SPECS_BY_MODE[ALLoopMode.ACTIVE_LEARNING])


def phase_for_mode(mode: ALLoopMode) -> LoopPhase:
    if mode == ALLoopMode.SIMULATION:
        return LoopPhase.SIM_BOOTSTRAP
    if mode == ALLoopMode.MANUAL:
        return LoopPhase.MANUAL_IDLE
    return LoopPhase.AL_BOOTSTRAP


@dataclass(slots=True)
class LoopTerminalDecision:
    set_status: ALLoopStatus | None = None
    set_phase: LoopPhase | None = None
    set_last_error: str | None = None
    create_next_job: bool = False


class LoopModePolicy(Protocol):
    def on_terminal(self, *, loop, sim_finished: bool) -> LoopTerminalDecision:
        ...


class ActiveLearningModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool) -> LoopTerminalDecision:  # noqa: ARG002
        if loop.current_iteration >= loop.max_rounds:
            return LoopTerminalDecision(set_status=ALLoopStatus.COMPLETED, set_phase=LoopPhase.AL_EVAL)
        return LoopTerminalDecision(create_next_job=True)


class SimulationModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool) -> LoopTerminalDecision:
        if loop.current_iteration >= loop.max_rounds or sim_finished:
            return LoopTerminalDecision(set_status=ALLoopStatus.COMPLETED, set_phase=LoopPhase.SIM_EVAL)
        return LoopTerminalDecision(create_next_job=True)


class ManualModePolicy:
    def on_terminal(self, *, loop, sim_finished: bool) -> LoopTerminalDecision:  # noqa: ARG002
        if loop.phase == LoopPhase.MANUAL_TASK_RUNNING:
            return LoopTerminalDecision(set_phase=LoopPhase.MANUAL_WAIT_CONFIRM)
        if loop.phase == LoopPhase.MANUAL_FINALIZE:
            if loop.current_iteration >= loop.max_rounds:
                return LoopTerminalDecision(set_status=ALLoopStatus.COMPLETED)
            return LoopTerminalDecision(create_next_job=True)
        if loop.phase == LoopPhase.MANUAL_IDLE:
            return LoopTerminalDecision(create_next_job=True)
        return LoopTerminalDecision()


DEFAULT_MODE_POLICIES: dict[ALLoopMode, LoopModePolicy] = {
    ALLoopMode.ACTIVE_LEARNING: ActiveLearningModePolicy(),
    ALLoopMode.SIMULATION: SimulationModePolicy(),
    ALLoopMode.MANUAL: ManualModePolicy(),
}

