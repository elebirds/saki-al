from __future__ import annotations

from typing import Any

from saki_executor.runtime.capability.cuda_nvml_provider import probe_cuda_devices


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_probe_cuda_devices_parses_nvidia_smi_output_when_returncode_zero(monkeypatch: Any) -> None:
    def _fake_run(*args: Any, **kwargs: Any) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(
            returncode=0,
            stdout="0, NVIDIA GeForce RTX 4060 Ti, 16380, 591.44\n",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)

    devices, driver_info = probe_cuda_devices()

    assert devices == [{"id": "0", "name": "NVIDIA GeForce RTX 4060 Ti", "memory_mb": 16380}]
    assert driver_info == {"provider": "nvidia-smi", "driver_version": "591.44"}
