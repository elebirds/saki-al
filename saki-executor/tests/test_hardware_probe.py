from __future__ import annotations

import types

from saki_executor import hardware as probe


def test_probe_hardware_cpu_only(monkeypatch):
    monkeypatch.setattr(probe, "HostProbeService", lambda: types.SimpleNamespace(
        probe=lambda **_kwargs: types.SimpleNamespace(
            cpu_workers=6,
            memory_mb=256,
            gpus=[],
            metal_available=False,
            platform="darwin",
            arch="arm64",
            driver_info={},
            to_dict=lambda: {
                "cpu_workers": 6,
                "memory_mb": 256,
                "gpus": [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            },
        ),
        to_resource_payload=lambda snapshot: {
            "gpu_count": len(snapshot.gpus),
            "gpu_device_ids": [],
            "cpu_workers": snapshot.cpu_workers,
            "memory_mb": snapshot.memory_mb,
            "accelerators": [
                {"type": "mps", "available": False, "device_count": 0, "device_ids": []},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
            "host_capability": snapshot.to_dict(),
        },
    ))

    payload = probe.probe_hardware(cpu_workers=6, memory_mb=256)
    assert payload["gpu_count"] == 0
    assert payload["cpu_workers"] == 6
    assert payload["memory_mb"] == 256
    assert any(item["type"] == "cpu" and item["available"] for item in payload["accelerators"])
    assert probe.available_accelerators(payload) == {"cpu"}


def test_probe_hardware_cuda_and_mps(monkeypatch):
    monkeypatch.setattr(probe, "HostProbeService", lambda: types.SimpleNamespace(
        probe=lambda **_kwargs: types.SimpleNamespace(
            cpu_workers=2,
            memory_mb=1024,
            gpus=[types.SimpleNamespace(id="0"), types.SimpleNamespace(id="1")],
            metal_available=True,
            platform="darwin",
            arch="arm64",
            driver_info={},
            to_dict=lambda: {
                "cpu_workers": 2,
                "memory_mb": 1024,
                "gpus": [{"id": "0"}, {"id": "1"}],
                "metal_available": True,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            },
        ),
        to_resource_payload=lambda snapshot: {
            "gpu_count": len(snapshot.gpus),
            "gpu_device_ids": [0, 1],
            "cpu_workers": snapshot.cpu_workers,
            "memory_mb": snapshot.memory_mb,
            "accelerators": [
                {"type": "cuda", "available": True, "device_count": 2, "device_ids": ["0", "1"]},
                {"type": "mps", "available": True, "device_count": 1, "device_ids": ["mps"]},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
            "host_capability": snapshot.to_dict(),
        },
    ))

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
