from __future__ import annotations

import sys
import types

from saki_executor.hardware import probe


def test_probe_hardware_cpu_only(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())
    monkeypatch.setattr(
        probe,
        "_probe_cuda",
        lambda _torch: {"type": "cuda", "available": False, "device_count": 0, "device_ids": []},
    )
    monkeypatch.setattr(
        probe,
        "_probe_mps",
        lambda _torch: {"type": "mps", "available": False, "device_count": 0, "device_ids": []},
    )

    payload = probe.probe_hardware(cpu_workers=6, memory_mb=256)
    assert payload["gpu_count"] == 0
    assert payload["cpu_workers"] == 6
    assert payload["memory_mb"] == 256
    assert any(item["type"] == "cpu" and item["available"] for item in payload["accelerators"])
    assert probe.available_accelerators(payload) == {"cpu"}


def test_probe_hardware_cuda_and_mps(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())
    monkeypatch.setattr(
        probe,
        "_probe_cuda",
        lambda _torch: {"type": "cuda", "available": True, "device_count": 2, "device_ids": ["0", "1"]},
    )
    monkeypatch.setattr(
        probe,
        "_probe_mps",
        lambda _torch: {"type": "mps", "available": True, "device_count": 1, "device_ids": ["mps"]},
    )

    payload = probe.probe_hardware(cpu_workers=2, memory_mb=1024)
    assert payload["gpu_count"] == 2
    assert payload["gpu_device_ids"] == [0, 1]
    assert probe.available_accelerators(payload) == {"cuda", "mps", "cpu"}


def test_normalize_accelerator_name():
    assert probe.normalize_accelerator_name("0") == "cuda"
    assert probe.normalize_accelerator_name("0,1") == "cuda"
    assert probe.normalize_accelerator_name("cuda:0") == "cuda"
    assert probe.normalize_accelerator_name("cpu") == "cpu"
    assert probe.normalize_accelerator_name("mps") == "mps"
