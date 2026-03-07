from __future__ import annotations

import pytest

from saki_api.modules.runtime.domain.loop_mode import phase_for_mode
from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase


def test_phase_for_mode_mapping():
    assert phase_for_mode(LoopMode.ACTIVE_LEARNING) == LoopPhase.AL_BOOTSTRAP
    assert phase_for_mode(LoopMode.SIMULATION) == LoopPhase.SIM_BOOTSTRAP
    assert phase_for_mode(LoopMode.MANUAL) == LoopPhase.MANUAL_BOOTSTRAP


def test_phase_for_mode_unknown_rejected():
    with pytest.raises(ValueError, match="unsupported loop mode"):
        phase_for_mode("unexpected_mode")  # type: ignore[arg-type]
