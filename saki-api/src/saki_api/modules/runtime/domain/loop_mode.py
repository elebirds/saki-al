"""Runtime loop-mode domain rules."""

from __future__ import annotations

from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase, StepType

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
    try:
        return LOOP_STEP_SPECS_BY_MODE[mode]
    except KeyError as exc:
        raise ValueError(f"unsupported loop mode for step specs: {mode}") from exc


def phase_for_mode(mode: LoopMode) -> LoopPhase:
    if mode == LoopMode.SIMULATION:
        return LoopPhase.SIM_BOOTSTRAP
    if mode == LoopMode.MANUAL:
        return LoopPhase.MANUAL_BOOTSTRAP
    return LoopPhase.AL_BOOTSTRAP
