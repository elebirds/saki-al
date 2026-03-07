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


def _is_python_script(cmd: list[str], python_path: Path, marker: str) -> bool:
    return bool(cmd and cmd[0] == str(python_path) and len(cmd) >= 3 and marker in cmd[2])


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
    )

    # 未安装 mmcv 时不应触发 onedl-mmcv 重装。
    assert not any(cmd[:3] == ["uv", "pip", "install"] for cmd in commands)


def test_sync_profile_env_repair_with_locked_wheel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    wheel_url = "https://mmwheels-bucket.onedl.ai/cu129-torch290/onedl-mmcv/onedl_mmcv-2.3.2.post2-cp312-cp312-manylinux_2_34_x86_64.whl"
    (plugin_dir / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "onedl-mmcv"',
                "wheels = [",
                f'  {{ url = "{wheel_url}" }},',
                "]",
            ]
        ),
        encoding="utf-8",
    )

    probe_payloads = [
        '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": false}\n',
        '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": true}\n',
    ]
    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(cmd, 0, probe_payloads.pop(0), "")
        if cmd[:3] == ["uv", "pip", "install"] and wheel_url in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
    )

    # 关键验证：使用 lock 中 wheel 直装，不走源码编译。
    assert any(cmd[:3] == ["uv", "pip", "install"] and wheel_url in cmd for cmd in commands)
    assert not any(any("onedl-mmcv==" in item for item in cmd) for cmd in commands)


def test_sync_profile_env_raises_when_no_locked_wheel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        installer.sync_profile_env(
            plugin_dir=plugin_dir,
            venv_dir=venv_dir,
            dependency_groups=["profile-cuda"],
        )

    message = str(exc_info.value)
    assert "prebuilt wheel repair failed" in message
    assert "locked_wheel_attempt=skipped(no_locked_wheel)" in message


def test_sync_profile_env_raises_when_auto_repair_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": false}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        installer.sync_profile_env(
            plugin_dir=plugin_dir,
            venv_dir=venv_dir,
            dependency_groups=["profile-cuda"],
            mm_ext_auto_repair=False,
        )

    message = str(exc_info.value)
    assert "auto repair is disabled" in message
    assert "only supports prebuilt wheel repair" in message


def test_sync_profile_env_profile_env_applies_to_sync_and_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = plugin_dir / ".venv-cuda"
    venv_python = _write_fake_venv_python(venv_dir)

    wheel_url = "https://mmwheels-bucket.onedl.ai/cu129-torch290/onedl-mmcv/onedl_mmcv-2.3.2.post2-cp312-cp312-manylinux_2_34_x86_64.whl"
    (plugin_dir / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "onedl-mmcv"',
                "wheels = [",
                f'  {{ url = "{wheel_url}" }},',
                "]",
            ]
        ),
        encoding="utf-8",
    )

    sync_env: dict[str, str] = {}
    repair_env: dict[str, str] = {}
    probe_payloads = [
        '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": false}\n',
        '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": true}\n',
    ]

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env", {})
        if cmd[:2] == ["uv", "sync"]:
            sync_env.update(env)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_python_script(cmd, venv_python, "__SAKI_MM_EXT_PROBE__"):
            return subprocess.CompletedProcess(cmd, 0, probe_payloads.pop(0), "")
        if cmd[:3] == ["uv", "pip", "install"] and wheel_url in cmd:
            repair_env.update(env)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    installer.sync_profile_env(
        plugin_dir=plugin_dir,
        venv_dir=venv_dir,
        dependency_groups=["profile-cuda"],
        profile_env={"CUSTOM_FLAG": "on"},
    )

    assert sync_env.get("CUSTOM_FLAG") == "on"
    assert repair_env.get("CUSTOM_FLAG") == "on"
