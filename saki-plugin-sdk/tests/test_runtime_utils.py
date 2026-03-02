from __future__ import annotations

from saki_plugin_sdk import available_accelerators, probe_hardware, resolve_train_val_split


def test_data_split_is_deterministic_and_handles_small_dataset():
    sample_ids = [f"s{i}" for i in range(10)]
    split_a = resolve_train_val_split(sample_ids=sample_ids, split_seed=7, val_ratio=0.2)
    split_b = resolve_train_val_split(sample_ids=sample_ids, split_seed=7, val_ratio=0.2)
    assert split_a == split_b
    train_ids, val_ids, degraded = resolve_train_val_split(sample_ids=["a", "b", "c"], split_seed=1, val_ratio=0.2)
    assert degraded is True
    assert train_ids == {"a", "b", "c"}
    assert val_ids == set()


def test_hardware_probe_contains_cpu_and_available_accelerators_fallback():
    payload = probe_hardware(cpu_workers=4, memory_mb=8192)
    assert payload["cpu_workers"] == 4
    assert payload["memory_mb"] == 8192
    accelerators = payload.get("accelerators") or []
    assert any(str(item.get("type")) == "cpu" and bool(item.get("available")) for item in accelerators)
    available = available_accelerators(payload)
    assert "cpu" in available
