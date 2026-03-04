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


def test_sync_profile_env_skip_repair_when_mmcv_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_EXT_PROBE__" in cmd[2]:
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
    )

    # 关键验证：未安装 mmcv 时不触发 onedl-mmcv 重建，避免无效额外耗时。
    assert not any(cmd[:3] == ["uv", "pip", "install"] for cmd in commands)


def test_sync_profile_env_repair_mmcv_ext_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    probe_payloads = [
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": false}\n",
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": true}\n",
    ]
    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_EXT_PROBE__" in cmd[2]:
            payload = probe_payloads.pop(0)
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_VERSION__" in cmd[2]:
            return subprocess.CompletedProcess(cmd, 0, "__SAKI_MM_VERSION__=2.3.2.post2\n", "")
        if cmd[:3] == ["uv", "pip", "install"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
    )

    rebuild_cmd = next(
        cmd for cmd in commands if cmd[:3] == ["uv", "pip", "install"] and any("onedl-mmcv==" in item for item in cmd)
    )
    # 关键验证：重建命令必须使用 no-build-isolation/no-cache/no-deps 组合。
    assert "--reinstall-package" in rebuild_cmd
    assert "onedl-mmcv" in rebuild_cmd
    assert "--no-build-isolation" in rebuild_cmd
    assert "--no-cache" in rebuild_cmd
    assert "--no-deps" in rebuild_cmd


def test_sync_profile_env_raises_when_repair_still_missing_ext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    probe_payloads = [
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": false}\n",
        "__SAKI_MM_EXT_PROBE__={\"has_mmcv\": true, \"has_mmcv_ext\": false}\n",
    ]

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_EXT_PROBE__" in cmd[2]:
            payload = probe_payloads.pop(0)
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_VERSION__" in cmd[2]:
            return subprocess.CompletedProcess(cmd, 0, "__SAKI_MM_VERSION__=2.3.2.post2\n", "")
        if cmd[:3] == ["uv", "pip", "install"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="missing mmcv\\._ext after auto repair attempt"):
        installer.sync_profile_env(
            plugin_dir=plugin_dir,
            venv_dir=venv_dir,
            dependency_groups=["profile-cuda"],
        )


def test_sync_profile_env_aligns_cuda_before_mmcv_rebuild(
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
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_TORCH_CUDA__" in cmd[2]:
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
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_EXT_PROBE__" in cmd[2]:
            payload = probe_payloads.pop(0)
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if cmd and cmd[0] == str(venv_python) and len(cmd) >= 3 and "__SAKI_MM_VERSION__" in cmd[2]:
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
        is_cuda_profile=True,
        cuda_toolchain_search_paths=[search_root],
    )

    # 关键验证：rebuild 阶段已经注入对齐后的 CUDA_HOME/PATH。
    assert rebuild_env.get("CUDA_HOME") == str(matched_home)
    assert rebuild_env.get("PATH", "").startswith(f"{matched_home / 'bin'}:")
    # 关键验证：先完成 toolchain 对齐，再执行 mmcv 重建。
    align_idx = commands.index([str(matched_home / "bin" / "nvcc"), "--version"])
    rebuild_idx = next(idx for idx, cmd in enumerate(commands) if any("onedl-mmcv==" in item for item in cmd))
    assert align_idx < rebuild_idx
