"""Runtime loop-mode domain rules."""

from __future__ import annotations

from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase


def phase_for_mode(mode: LoopMode) -> LoopPhase:
    if mode == LoopMode.SIMULATION:
        return LoopPhase.SIM_BOOTSTRAP
    if mode == LoopMode.MANUAL:
        return LoopPhase.MANUAL_BOOTSTRAP
    return LoopPhase.AL_BOOTSTRAP
