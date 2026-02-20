from __future__ import annotations

import pytest

from saki_api.modules.runtime.domain.loop_mode import step_specs_for_mode
from saki_api.modules.shared.modeling.enums import LoopMode, StepType


def test_step_specs_for_mode_exact_mapping():
    assert step_specs_for_mode(LoopMode.ACTIVE_LEARNING) == (
        StepType.TRAIN,
        StepType.SCORE,
        StepType.EVAL,
        StepType.SELECT,
    )
    assert step_specs_for_mode(LoopMode.SIMULATION) == (
        StepType.TRAIN,
        StepType.SCORE,
        StepType.EVAL,
        StepType.SELECT,
        StepType.ACTIVATE_SAMPLES,
        StepType.ADVANCE_BRANCH,
    )
    assert step_specs_for_mode(LoopMode.MANUAL) == (
        StepType.TRAIN,
        StepType.EVAL,
        StepType.EXPORT,
    )


def test_step_specs_for_mode_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unsupported loop mode"):
        step_specs_for_mode("unexpected_mode")  # type: ignore[arg-type]
