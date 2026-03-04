from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from saki_executor.runtime.environment import uv_profile_installer as installer


def _write_fake_venv_python(venv_dir: Path) -> Path:
    python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    return python_path


def _create_fake_cuda_home(root: Path, name: str) -> Path:
    home = root / name
    nvcc = home / "bin" / "nvcc"
    nvcc.parent.mkdir(parents=True, exist_ok=True)
    nvcc.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return home


def _is_python_script(cmd: list[str], python_path: Path, marker: str) -> bool:
    return bool(cmd and cmd[0] == str(python_path) and len(cmd) >= 3 and marker in cmd[2])


def test_non_cuda_profile_does_not_trigger_toolchain_align(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cpu"
    venv_python = _write_fake_venv_python(venv_dir)

    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": false, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cpu"],
        is_cuda_profile=False,
    )

    # 非 CUDA profile 下不应触发 torch/nvcc 探测。
    assert not any("__SAKI_TORCH_CUDA__" in (cmd[2] if len(cmd) > 2 else "") for cmd in commands)
    assert not any((cmd and cmd[0] == "nvcc") for cmd in commands)


def test_cuda_profile_skips_align_when_torch_cuda_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_TORCH_CUDA__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_TORCH_CUDA__={"torch_cuda": "", "torch_version": "2.10.0"}\n',
                "",
            )
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": false, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
        is_cuda_profile=True,
    )

    assert not any((cmd and cmd[0] == "nvcc") for cmd in commands)
    assert not any("nvidia-cuda-nvcc-cu" in " ".join(cmd) for cmd in commands)


def test_cuda_profile_selects_matching_home_and_injects_env_for_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)
    search_root = tmp_path / "search"
    matched_home = _create_fake_cuda_home(search_root, "cuda-12.8")

    probe_payloads = [
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": false}\n",
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": true}\n",
    ]
    commands: list[list[str]] = []
    rebuild_env: dict[str, str] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        env = kwargs.get("env", {})
        if cmd[:2] == ["uv", "sync"]:
            assert env.get("CUSTOM_FLAG") == "on"
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_TORCH_CUDA__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_TORCH_CUDA__={"torch_cuda": "12.8", "torch_version": "2.10.0+cu128"}\n',
                "",
            )
        if cmd == ["nvcc", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "Cuda compilation tools, release 13.1, V13.1.0", "")
        if cmd == [str(matched_home / "bin" / "nvcc"), "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "Cuda compilation tools, release 12.8, V12.8.0", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            payload = probe_payloads.pop(0)
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_VERSION__"):
            return subprocess.CompletedProcess(cmd, 0, "__SAKI_MM_VERSION__=2.3.2.post2\n", "")
        if cmd[:3] == ["uv", "pip", "install"]:
            if any("onedl-mmcv==" in item for item in cmd):
                rebuild_env.update(env)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
        profile_env={"CUSTOM_FLAG": "on"},
        is_cuda_profile=True,
        cuda_toolchain_search_paths=[search_root],
    )

    assert rebuild_env.get("CUDA_HOME") == str(matched_home)
    assert rebuild_env.get("PATH", "").startswith(f"{matched_home / 'bin'}:")
    align_idx = commands.index([str(matched_home / "bin" / "nvcc"), "--version"])
    rebuild_idx = next(idx for idx, cmd in enumerate(commands) if any("onedl-mmcv==" in item for item in cmd))
    assert align_idx < rebuild_idx


def test_cuda_profile_auto_installs_nvcc_when_no_matching_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)
    search_root = tmp_path / "search"

    installed_home = venv_dir / "lib" / "python3.12" / "site-packages" / "nvidia" / "cuda_nvcc"
    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_TORCH_CUDA__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_TORCH_CUDA__={"torch_cuda": "12.8", "torch_version": "2.10.0+cu128"}\n',
                "",
            )
        if cmd == ["nvcc", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "Cuda compilation tools, release 13.1, V13.1.0", "")
        if cmd[:3] == ["uv", "pip", "install"] and "nvidia-cuda-nvcc-cu12" in cmd:
            _create_fake_cuda_home(installed_home.parent, "cuda_nvcc")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd == [str(installed_home / "bin" / "nvcc"), "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "Cuda compilation tools, release 12.8, V12.8.0", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": false, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
        is_cuda_profile=True,
        cuda_toolchain_search_paths=[search_root],
        cuda_toolchain_auto_install_nvcc=True,
    )

    assert any(cmd[:3] == ["uv", "pip", "install"] and "nvidia-cuda-nvcc-cu12" in cmd for cmd in commands)


def test_cuda_profile_auto_install_failure_reports_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_TORCH_CUDA__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_TORCH_CUDA__={"torch_cuda": "12.8", "torch_version": "2.10.0+cu128"}\n',
                "",
            )
        if cmd == ["nvcc", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "Cuda compilation tools, release 13.1, V13.1.0", "")
        if cmd[:3] == ["uv", "pip", "install"] and "nvidia-cuda-nvcc-cu12" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "mock install failed")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": false, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        installer.sync_profile_env(
            plugin_dir=plugin_dir,
            venv_dir=venv_dir,
            dependency_groups=["profile-cuda"],
            is_cuda_profile=True,
            cuda_toolchain_auto_install_nvcc=True,
            cuda_toolchain_search_paths=[tmp_path / "search"],
        )

    message = str(exc_info.value)
    assert "failed to align CUDA toolchain" in message
    assert "torch_cuda=12.8" in message
    assert "nvcc_detected=13.1" in message
    assert "cuda_home_candidates=" in message
    assert "auto_install_attempted=True" in message
