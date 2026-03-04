from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_MM_EXT_PROBE_PREFIX = "__SAKI_MM_EXT_PROBE__="
_MM_VERSION_PREFIX = "__SAKI_MM_VERSION__="


def _tail(text: str, limit: int = 500) -> str:
    data = str(text or "").strip()
    if len(data) <= limit:
        return data
    return data[-limit:]


def _run_command(
    *,
    command: list[str],
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
        check=False,
    )


def _probe_mmcv_ext(
    *,
    venv_python: Path,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> tuple[bool, bool]:
    # 关键设计：用 importlib.find_spec 做“低侵入”探测，避免直接 import 触发更重副作用。
    script = """
import importlib.util
import json

def _has_spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

payload = {
    "has_mmcv": _has_spec("mmcv"),
    "has_mmcv_ext": _has_spec("mmcv._ext"),
}
print("__SAKI_MM_EXT_PROBE__=" + json.dumps(payload, ensure_ascii=True))
"""
    result = _run_command(
        command=[str(venv_python), "-c", script],
        cwd=cwd,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(result.returncode or 0) != 0:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: mmcv extension probe failed "
            f"exit_code={result.returncode} stderr={_tail(result.stderr)}"
        )

    for line in (result.stdout or "").splitlines():
        if not line.startswith(_MM_EXT_PROBE_PREFIX):
            continue
        payload = json.loads(line[len(_MM_EXT_PROBE_PREFIX) :].strip() or "{}")
        return bool(payload.get("has_mmcv")), bool(payload.get("has_mmcv_ext"))

    raise RuntimeError(
        "PROFILE_UNSATISFIED: mmcv extension probe returned no marker "
        f"stdout={_tail(result.stdout)}"
    )


def _read_onedl_mmcv_version(
    *,
    venv_python: Path,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> str:
    script = """
try:
    from importlib import metadata as importlib_metadata
except Exception:
    import importlib_metadata  # type: ignore

version = ""
try:
    version = str(importlib_metadata.version("onedl-mmcv") or "").strip()
except Exception:
    version = ""
print("__SAKI_MM_VERSION__=" + version)
"""
    result = _run_command(
        command=[str(venv_python), "-c", script],
        cwd=cwd,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(result.returncode or 0) != 0:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: failed to read onedl-mmcv version "
            f"exit_code={result.returncode} stderr={_tail(result.stderr)}"
        )

    for line in (result.stdout or "").splitlines():
        if line.startswith(_MM_VERSION_PREFIX):
            return str(line[len(_MM_VERSION_PREFIX) :].strip())
    return ""


def _repair_mmcv_ext(
    *,
    plugin_dir: Path,
    venv_python: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> tuple[str, str]:
    # 先补齐构建工具，确保后续 --no-build-isolation 重建 onedl-mmcv 时依赖可用。
    bootstrap = _run_command(
        command=[
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_python),
            "setuptools",
            "wheel",
            "packaging",
        ],
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(bootstrap.returncode or 0) != 0:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: mmcv._ext missing and bootstrap install failed "
            f"stderr={_tail(bootstrap.stderr)}"
        )

    version = _read_onedl_mmcv_version(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if not version:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: mmcv._ext missing but installed onedl-mmcv version is unavailable"
        )

    rebuild = _run_command(
        command=[
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_python),
            "--no-build-isolation",
            "--no-cache",
            "--no-deps",
            f"onedl-mmcv=={version}",
        ],
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(rebuild.returncode or 0) != 0:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: mmcv._ext missing and rebuild failed "
            f"stderr={_tail(rebuild.stderr)}"
        )

    return _tail(bootstrap.stderr), _tail(rebuild.stderr)


def sync_profile_env(
    *,
    plugin_dir: Path,
    venv_dir: Path,
    dependency_groups: list[str],
    timeout_sec: int = 900,
    mm_ext_auto_repair: bool = True,
    mm_ext_auto_repair_timeout_sec: int = 1200,
) -> None:
    command = ["uv", "sync"]
    for group in dependency_groups:
        value = str(group or "").strip()
        if not value:
            continue
        command.extend(["--extra", value])

    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
    result = _run_command(
        command=command,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(result.returncode or 0) != 0:
        raise RuntimeError(
            f"PROFILE_UNSATISFIED: uv sync failed for profile env plugin_dir={plugin_dir} "
            f"venv={venv_dir} exit_code={result.returncode} stderr={_tail(result.stderr)}"
        )

    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        # 解释：解释器路径缺失属于上游环境问题，这里保持原有语义，交给调用方统一报错。
        return

    has_mmcv, has_mmcv_ext = _probe_mmcv_ext(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if (not has_mmcv) or has_mmcv_ext:
        return

    if not bool(mm_ext_auto_repair):
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext after uv sync; "
            "auto repair is disabled, set PLUGIN_MM_EXT_AUTO_REPAIR=true or rebuild onedl-mmcv manually"
        )

    bootstrap_stderr = ""
    rebuild_stderr = ""
    try:
        bootstrap_stderr, rebuild_stderr = _repair_mmcv_ext(
            plugin_dir=plugin_dir,
            venv_python=venv_python,
            timeout_sec=max(60, int(mm_ext_auto_repair_timeout_sec)),
            env=env,
        )
    except Exception as exc:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext and auto repair failed "
            f"(attempted rebuild with --no-build-isolation). reason={exc}"
        ) from exc

    _, repaired_has_ext = _probe_mmcv_ext(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=env,
    )
    if not repaired_has_ext:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext after auto repair attempt; "
            f"bootstrap_stderr={bootstrap_stderr!r} rebuild_stderr={rebuild_stderr!r}"
        )
