from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

_MM_EXT_PROBE_PREFIX = "__SAKI_MM_EXT_PROBE__="


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


def _merge_env(base: dict[str, str], overlay: dict[str, str] | None = None) -> dict[str, str]:
    # 关键设计：profile env 必须在 sync 阶段生效，保证环境同步与 worker 运行时一致。
    env = dict(base)
    for key, value in (overlay or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        env[name] = str(value or "")
    return env


def _extract_locked_mmcv_wheel_urls(lock_path: Path) -> list[str]:
    """从 uv.lock 的 onedl-mmcv 包块提取 wheel URL。

    只提取 wheel，不提取 sdist。这样可避免触发源码编译路径。
    """
    if not lock_path.exists():
        return []

    urls: list[str] = []
    in_mmcv_block = False
    block_seen_name = False
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        line = str(raw or "").strip()
        if line == "[[package]]":
            if in_mmcv_block:
                break
            in_mmcv_block = False
            block_seen_name = False
            continue
        if line.startswith("name = "):
            block_seen_name = True
            in_mmcv_block = line == 'name = "onedl-mmcv"'
            continue
        if not in_mmcv_block or not block_seen_name:
            continue
        if '.whl"' not in line or 'url = "' not in line:
            continue
        match = re.search(r'url\s*=\s*"([^"]+\.whl)"', line)
        if match:
            urls.append(match.group(1))
    return urls


def _probe_mmcv_ext(
    *,
    venv_python: Path,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> tuple[bool, bool]:
    # 关键设计：用 find_spec 进行无副作用探测，避免 import 期间触发重依赖初始化。
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


def _try_install_locked_mmcv_wheel(
    *,
    plugin_dir: Path,
    venv_python: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> str:
    # 关键设计：只允许按 lock 中已解析好的预编译 wheel 重装，不走源码编译链路。
    lock_path = plugin_dir / "uv.lock"
    wheel_urls = _extract_locked_mmcv_wheel_urls(lock_path)
    if not wheel_urls:
        return "skipped(no_locked_wheel)"

    last_error = ""
    for url in wheel_urls:
        install = _run_command(
            command=[
                "uv",
                "pip",
                "install",
                "--python",
                str(venv_python),
                "--reinstall-package",
                "onedl-mmcv",
                "--no-deps",
                "--no-cache",
                url,
            ],
            cwd=plugin_dir,
            timeout_sec=timeout_sec,
            env=env,
        )
        if int(install.returncode or 0) != 0:
            last_error = f"url={url} stderr={_tail(install.stderr)}"
            continue

        _, has_ext = _probe_mmcv_ext(
            venv_python=venv_python,
            cwd=plugin_dir,
            timeout_sec=timeout_sec,
            env=env,
        )
        if has_ext:
            return f"installed(url={url})"
        last_error = f"url={url} installed_but_ext_missing"

    if last_error:
        return f"failed({last_error})"
    return "failed(no_candidate_succeeded)"


def sync_profile_env(
    *,
    plugin_dir: Path,
    venv_dir: Path,
    dependency_groups: list[str],
    timeout_sec: int = 900,
    profile_env: dict[str, str] | None = None,
    mm_ext_auto_repair: bool = True,
    mm_ext_auto_repair_timeout_sec: int = 1200,
) -> None:
    command = ["uv", "sync"]
    for group in dependency_groups:
        value = str(group or "").strip()
        if not value:
            continue
        command.extend(["--extra", value])

    env = _merge_env(dict(os.environ), profile_env)
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

    # 关键设计：实验分支仅保留“预编译 wheel 直装修复”。
    # 不再执行 CUDA toolchain 对齐与源码重编译，避免引入 nvcc 版本耦合。
    if not bool(mm_ext_auto_repair):
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext after uv sync; "
            "auto repair is disabled, and this branch only supports prebuilt wheel repair. "
            "please ensure uv.lock contains a prebuilt onedl-mmcv wheel with mmcv._ext"
        )

    locked_wheel_attempt = _try_install_locked_mmcv_wheel(
        plugin_dir=plugin_dir,
        venv_python=venv_python,
        timeout_sec=max(60, int(mm_ext_auto_repair_timeout_sec)),
        env=env,
    )
    if locked_wheel_attempt.startswith("installed("):
        return

    raise RuntimeError(
        "PROFILE_UNSATISFIED: missing mmcv._ext and prebuilt wheel repair failed; "
        "no source-build fallback is enabled in this branch. "
        f"locked_wheel_attempt={locked_wheel_attempt}"
    )
