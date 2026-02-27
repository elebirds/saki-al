"""Runtime loop-mode domain rules."""

from __future__ import annotations

from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase, LoopStage


def phase_for_mode(mode: LoopMode) -> LoopPhase:
    if mode == LoopMode.ACTIVE_LEARNING:
        return LoopPhase.AL_BOOTSTRAP
    if mode == LoopMode.SIMULATION:
        return LoopPhase.SIM_BOOTSTRAP
    if mode == LoopMode.MANUAL:
        return LoopPhase.MANUAL_BOOTSTRAP
    raise ValueError(f"unsupported loop mode for phase mapping: {mode}")


def stage_for_mode(mode: LoopMode) -> LoopStage:
    if mode == LoopMode.ACTIVE_LEARNING:
        return LoopStage.SNAPSHOT_REQUIRED
    if mode in {LoopMode.SIMULATION, LoopMode.MANUAL}:
        return LoopStage.READY_TO_START
    raise ValueError(f"unsupported loop mode for stage mapping: {mode}")
