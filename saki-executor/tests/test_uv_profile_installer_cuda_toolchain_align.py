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


def _is_probe_script(cmd: list[str], python_path: Path) -> bool:
    return bool(cmd and cmd[0] == str(python_path) and len(cmd) >= 3 and "__SAKI_MM_EXT_PROBE__" in cmd[2])


def test_extract_locked_mmcv_wheel_urls_reads_only_mmcv_block(tmp_path: Path) -> None:
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "numpy"',
                "wheels = [",
                '  { url = "https://example.com/numpy.whl" },',
                "]",
                "[[package]]",
                'name = "onedl-mmcv"',
                "wheels = [",
                '  { url = "https://example.com/mmcv-a.whl" },',
                '  { url = "https://example.com/mmcv-b.whl" },',
                "]",
                "[[package]]",
                'name = "torch"',
                "wheels = [",
                '  { url = "https://example.com/torch.whl" },',
                "]",
            ]
        ),
        encoding="utf-8",
    )

    urls = installer._extract_locked_mmcv_wheel_urls(lock_path)
    assert urls == ["https://example.com/mmcv-a.whl", "https://example.com/mmcv-b.whl"]


def test_try_install_locked_mmcv_wheel_tries_multiple_urls_until_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_python = _write_fake_venv_python(plugin_dir / ".venv-cuda")

    url_a = "https://example.com/mmcv-a.whl"
    url_b = "https://example.com/mmcv-b.whl"
    (plugin_dir / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "onedl-mmcv"',
                "wheels = [",
                f'  {{ url = "{url_a}" }},',
                f'  {{ url = "{url_b}" }},',
                "]",
            ]
        ),
        encoding="utf-8",
    )

    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:3] == ["uv", "pip", "install"] and url_a in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "download failed")
        if cmd[:3] == ["uv", "pip", "install"] and url_b in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _is_probe_script(cmd, venv_python):
            return subprocess.CompletedProcess(
                cmd,
                0,
                '__SAKI_MM_EXT_PROBE__={"has_mmcv": true, "has_mmcv_ext": true}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = installer._try_install_locked_mmcv_wheel(
        plugin_dir=plugin_dir,
        venv_python=venv_python,
        timeout_sec=300,
        env={},
    )

    assert result == f"installed(url={url_b})"
    assert any(cmd[:3] == ["uv", "pip", "install"] and url_a in cmd for cmd in commands)
    assert any(cmd[:3] == ["uv", "pip", "install"] and url_b in cmd for cmd in commands)


def test_try_install_locked_mmcv_wheel_returns_failed_with_last_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    venv_python = _write_fake_venv_python(plugin_dir / ".venv-cuda")

    url = "https://example.com/mmcv-a.whl"
    (plugin_dir / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "onedl-mmcv"',
                "wheels = [",
                f'  {{ url = "{url}" }},',
                "]",
            ]
        ),
        encoding="utf-8",
    )

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["uv", "pip", "install"] and url in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "network unreachable")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = installer._try_install_locked_mmcv_wheel(
        plugin_dir=plugin_dir,
        venv_python=venv_python,
        timeout_sec=300,
        env={},
    )

    assert result.startswith("failed(url=https://example.com/mmcv-a.whl stderr=")
    assert "network unreachable" in result
