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
