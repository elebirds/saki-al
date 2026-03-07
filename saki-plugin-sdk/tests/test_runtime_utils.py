from __future__ import annotations

import pytest

from saki_plugin_sdk import (
    DevicePriorityStrategy,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    RuntimeProfileSpec,
    resolve_device_binding,
    resolve_train_val_split,
)


def test_data_split_is_deterministic_and_handles_small_dataset():
    sample_ids = [f"s{i}" for i in range(10)]
    split_a = resolve_train_val_split(sample_ids=sample_ids, split_seed=7, val_ratio=0.2)
    split_b = resolve_train_val_split(sample_ids=sample_ids, split_seed=7, val_ratio=0.2)
    assert split_a == split_b
    train_ids, val_ids, degraded = resolve_train_val_split(sample_ids=["a", "b", "c"], split_seed=1, val_ratio=0.2)
    assert degraded is True
    assert train_ids == {"a", "b", "c"}
    assert val_ids == set()


def test_device_binding_resolver_auto_and_explicit_conflict():
    host = HostCapabilitySnapshot.from_dict(
        {
            "cpu_workers": 8,
            "memory_mb": 16384,
            "gpus": [{"id": "0", "name": "GPU-0", "memory_mb": 8192}],
            "metal_available": False,
            "platform": "darwin",
            "arch": "arm64",
            "driver_info": {},
        }
    )
    runtime = RuntimeCapabilitySnapshot(
        framework="torch",
        framework_version="2.2.0",
        backends=["cpu", "cuda"],
        backend_details={},
        errors=[],
    )
    profile = RuntimeProfileSpec(
        id="cuda",
        priority=10,
        when="host.backends.includes('cuda')",
        dependency_groups=["profile-cuda"],
        allowed_backends=["cuda"],
    )

    binding = resolve_device_binding(
        requested_device="auto",
        host_capability=host,
        runtime_capability=runtime,
        supported_backends=["cuda", "cpu"],
        profile=profile,
        allow_auto_fallback=True,
        priority_strategy=DevicePriorityStrategy(("cuda", "cpu")),
    )
    assert binding.backend == "cuda"

    with pytest.raises(RuntimeError, match="DEVICE_BINDING_CONFLICT"):
        resolve_device_binding(
            requested_device="mps",
            host_capability=host,
            runtime_capability=runtime,
            supported_backends=["cuda", "cpu"],
            profile=profile,
            allow_auto_fallback=True,
            priority_strategy=DevicePriorityStrategy(("cuda", "cpu")),
        )
