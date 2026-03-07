from __future__ import annotations

import pytest

from saki_plugin_sdk import TaskRuntimeContext


def test_runtime_context_roundtrip():
    context = TaskRuntimeContext(
        task_id="step-7",
        round_id="round-7",
        round_index=3,
        attempt=2,
        task_type="score",
        mode="simulation",
        split_seed=101,
        train_seed=202,
        sampling_seed=303,
        resolved_device_backend="cuda",
    )
    payload = context.to_dict()
    rebuilt = TaskRuntimeContext.from_dict(payload)
    assert rebuilt == context


def test_runtime_context_rejects_missing_required_fields():
    with pytest.raises(ValueError):
        TaskRuntimeContext.from_dict({"mode": "simulation"})
