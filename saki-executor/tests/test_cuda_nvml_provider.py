from __future__ import annotations

from typing import Any

import pytest

from saki_executor.runtime.capability.cuda_nvml_provider import probe_cuda_devices


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_probe_cuda_devices_parses_nvidia_smi_output_when_returncode_zero(monkeypatch: Any) -> None:
    def _fake_run(*args: Any, **kwargs: Any) -> _FakeCompletedProcess:
        cmd = list(args[0] if args else [])
        if "--query-gpu=index,name,memory.total,driver_version,compute_cap,multiprocessor_count,clocks.max.sm" in cmd:
            return _FakeCompletedProcess(
                returncode=0,
                stdout="0, NVIDIA GeForce RTX 4060 Ti, 16380, 591.44, 8.9, 34, 2535\n",
                stderr="",
            )
        if cmd == ["nvidia-smi"]:
            return _FakeCompletedProcess(
                returncode=0,
                stdout=(
                    "Fri Mar  6 12:00:00 2026\n"
                    "| NVIDIA-SMI 591.44    Driver Version: 591.44    CUDA Version: 12.9 |\n"
                ),
                stderr="",
            )
        return _FakeCompletedProcess(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)

    devices, driver_info = probe_cuda_devices()

    assert len(devices) == 1
    assert devices[0]["id"] == "0"
    assert devices[0]["name"] == "NVIDIA GeForce RTX 4060 Ti"
    assert devices[0]["memory_mb"] == 16380
    assert devices[0]["compute_capability"] == "8.9"
    assert devices[0]["fp32_tflops"] == pytest.approx(22.065, abs=0.001)
    assert driver_info == {
        "provider": "nvidia-smi",
        "driver_version": "591.44",
        "cuda_version": "12.9",
    }


def test_probe_cuda_devices_fallbacks_to_basic_query_when_rich_query_failed(monkeypatch: Any) -> None:
    def _fake_run(*args: Any, **kwargs: Any) -> _FakeCompletedProcess:
        cmd = list(args[0] if args else [])
        if "--query-gpu=index,name,memory.total,driver_version,compute_cap,multiprocessor_count,clocks.max.sm" in cmd:
            return _FakeCompletedProcess(returncode=1, stderr="Unknown field")
        if "--query-gpu=index,name,memory.total,driver_version" in cmd:
            return _FakeCompletedProcess(
                returncode=0,
                stdout="0, Tesla T4, 15109, 550.54.15\n",
            )
        if cmd == ["nvidia-smi"]:
            return _FakeCompletedProcess(returncode=0, stdout="")
        return _FakeCompletedProcess(returncode=1, stderr="unexpected")

    monkeypatch.setattr("subprocess.run", _fake_run)

    devices, driver_info = probe_cuda_devices()

    assert devices == [
        {
            "id": "0",
            "name": "Tesla T4",
            "memory_mb": 15109,
            "compute_capability": "",
            "fp32_tflops": None,
        }
    ]
    assert driver_info == {
        "provider": "nvidia-smi",
        "driver_version": "550.54.15",
        "cuda_version": "",
    }
