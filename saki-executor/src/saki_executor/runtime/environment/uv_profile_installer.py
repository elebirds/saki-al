from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_MM_EXT_PROBE_PREFIX = "__SAKI_MM_EXT_PROBE__="
_MM_VERSION_PREFIX = "__SAKI_MM_VERSION__="
_TORCH_CUDA_PREFIX = "__SAKI_TORCH_CUDA__="


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
    # 关键设计：profile env 必须在 sync 阶段就生效，避免“worker 可见、sync 不可见”的隐性不一致。
    env = dict(base)
    for key, value in (overlay or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        env[name] = str(value or "")
    return env


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


def _probe_torch_cuda_version(
    *,
    venv_python: Path,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> tuple[str, str]:
    # 关键设计：不直接依赖 import torch 的成功与否，探测失败时返回空值并由上层决定是否跳过对齐。
    script = """
import json

payload = {"torch_cuda": "", "torch_version": ""}
try:
    import torch
    payload["torch_version"] = str(getattr(torch, "__version__", "") or "").strip()
    version_mod = getattr(torch, "version", None)
    cuda_version = getattr(version_mod, "cuda", None) if version_mod is not None else None
    payload["torch_cuda"] = str(cuda_version or "").strip()
except Exception:
    payload = {"torch_cuda": "", "torch_version": ""}
print("__SAKI_TORCH_CUDA__=" + json.dumps(payload, ensure_ascii=True))
"""
    result = _run_command(
        command=[str(venv_python), "-c", script],
        cwd=cwd,
        timeout_sec=timeout_sec,
        env=env,
    )
    if int(result.returncode or 0) != 0:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: failed to probe torch cuda version "
            f"exit_code={result.returncode} stderr={_tail(result.stderr)}"
        )

    for line in (result.stdout or "").splitlines():
        if not line.startswith(_TORCH_CUDA_PREFIX):
            continue
        payload = json.loads(line[len(_TORCH_CUDA_PREFIX) :].strip() or "{}")
        torch_cuda = str(payload.get("torch_cuda") or "").strip()
        torch_version = str(payload.get("torch_version") or "").strip()
        return torch_cuda, torch_version
    return "", ""


def _parse_cuda_version(raw: str) -> tuple[int, int | None] | None:
    value = str(raw or "").strip()
    if not value:
        return None
    match = re.search(r"(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    major = int(match.group(1))
    minor_raw = match.group(2)
    minor = int(minor_raw) if minor_raw is not None else None
    return major, minor


def _normalize_cuda_version(raw: str) -> str:
    parsed = _parse_cuda_version(raw)
    if parsed is None:
        return ""
    major, minor = parsed
    if minor is None:
        return str(major)
    return f"{major}.{minor}"


def _cuda_match_score(torch_cuda: str, candidate_cuda: str) -> int:
    torch_ver = _parse_cuda_version(torch_cuda)
    candidate_ver = _parse_cuda_version(candidate_cuda)
    if torch_ver is None or candidate_ver is None:
        return 0
    torch_major, torch_minor = torch_ver
    cand_major, cand_minor = candidate_ver
    if torch_major != cand_major:
        return 0
    if torch_minor is not None and cand_minor is not None and torch_minor == cand_minor:
        return 2
    return 1


def _probe_nvcc_version(
    *,
    command: list[str],
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> str:
    # 关键设计：统一用 `nvcc --version` 输出解析，所有候选路径共用该逻辑，便于后续复用到其他扩展重建场景。
    try:
        result = _run_command(command=command, cwd=cwd, timeout_sec=timeout_sec, env=env)
    except Exception:
        return ""
    if int(result.returncode or 0) != 0:
        return ""

    text = f"{result.stdout}\n{result.stderr}"
    release_match = re.search(r"release\s+(\d+\.\d+)", text)
    if release_match:
        return _normalize_cuda_version(release_match.group(1))
    version_match = re.search(r"V(\d+\.\d+(?:\.\d+)?)", text)
    if version_match:
        return _normalize_cuda_version(version_match.group(1))
    return ""


def _discover_venv_cuda_homes(venv_python: Path) -> list[Path]:
    venv_dir = venv_python.parent.parent
    lib_dir = venv_dir / "lib"
    if not lib_dir.exists():
        return []

    homes: list[Path] = []
    for py_lib in sorted(lib_dir.glob("python*")):
        nvidia_dir = py_lib / "site-packages" / "nvidia"
        if not nvidia_dir.exists():
            continue
        for candidate in sorted(nvidia_dir.glob("cuda_nvcc*")):
            homes.append(candidate)
    return homes


def _discover_cuda_homes(
    *,
    torch_cuda: str,
    profile_env: dict[str, str] | None,
    search_paths: list[Path],
    venv_python: Path,
) -> list[Path]:
    parsed = _parse_cuda_version(torch_cuda)
    major = parsed[0] if parsed is not None else None
    minor = parsed[1] if parsed is not None else None

    candidates: list[Path] = []
    profile_cuda_home = str((profile_env or {}).get("CUDA_HOME") or "").strip()
    if profile_cuda_home:
        candidates.append(Path(profile_cuda_home))

    if major is not None and minor is not None:
        candidates.append(Path(f"/usr/local/cuda-{major}.{minor}"))
    if major is not None:
        candidates.append(Path(f"/usr/local/cuda-{major}"))
    candidates.append(Path("/usr/local/cuda"))

    for root in search_paths:
        base = Path(str(root or "").strip())
        if not base.exists() or not base.is_dir():
            continue
        for item in sorted(base.glob("cuda*")):
            if item.is_dir():
                candidates.append(item)

    candidates.extend(_discover_venv_cuda_homes(venv_python))

    dedup: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return dedup


def _select_matching_cuda_home(
    *,
    torch_cuda: str,
    candidates: list[Path],
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> tuple[Path | None, str, list[str]]:
    best_home: Path | None = None
    best_version = ""
    best_score = 0
    attempted: list[str] = []

    for home in candidates:
        nvcc_path = home / "bin" / "nvcc"
        attempted.append(str(home))
        if not nvcc_path.exists():
            continue

        version = _probe_nvcc_version(
            command=[str(nvcc_path), "--version"],
            cwd=cwd,
            timeout_sec=timeout_sec,
            env=env,
        )
        score = _cuda_match_score(torch_cuda, version)
        if score > best_score:
            best_score = score
            best_home = home
            best_version = version
        if score == 2:
            break
    return best_home, best_version, attempted


def _prepend_path(path_value: str, prepend: str) -> str:
    original = str(path_value or "").strip()
    if not original:
        return prepend
    return f"{prepend}:{original}"


def _apply_cuda_home_env(base_env: dict[str, str], cuda_home: Path) -> dict[str, str]:
    aligned = dict(base_env)
    aligned["CUDA_HOME"] = str(cuda_home)
    aligned["PATH"] = _prepend_path(aligned.get("PATH", ""), str(cuda_home / "bin"))
    return aligned


def _format_cuda_alignment_context(context: dict[str, Any]) -> str:
    homes = context.get("cuda_home_candidates") or []
    homes_text = ",".join(str(item) for item in homes) if homes else "-"
    return (
        f"torch_cuda={context.get('torch_cuda') or '-'} "
        f"torch_version={context.get('torch_version') or '-'} "
        f"nvcc_detected={context.get('nvcc_detected') or '-'} "
        f"cuda_home_candidates={homes_text} "
        f"selected_cuda_home={context.get('selected_cuda_home') or '-'} "
        f"auto_install_attempted={bool(context.get('auto_install_attempted'))} "
        f"auto_install_result={context.get('auto_install_result') or '-'}"
    )


def _ensure_cuda_toolchain(
    *,
    plugin_dir: Path,
    venv_python: Path,
    env: dict[str, str],
    profile_env: dict[str, str] | None,
    auto_install_nvcc: bool,
    timeout_sec: int,
    search_paths: list[Path],
) -> tuple[dict[str, str], dict[str, Any]]:
    context: dict[str, Any] = {
        "torch_cuda": "",
        "torch_version": "",
        "nvcc_detected": "",
        "cuda_home_candidates": [],
        "selected_cuda_home": "",
        "auto_install_attempted": False,
        "auto_install_result": "skipped",
    }
    aligned_env = dict(env)

    torch_cuda, torch_version = _probe_torch_cuda_version(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    context["torch_cuda"] = torch_cuda
    context["torch_version"] = torch_version
    if not torch_cuda:
        # 非 CUDA torch 或 torch 尚未就绪时直接跳过，避免对 CPU/MPS 场景产生副作用。
        return aligned_env, context

    nvcc_detected = _probe_nvcc_version(
        command=["nvcc", "--version"],
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    context["nvcc_detected"] = nvcc_detected
    if _cuda_match_score(torch_cuda, nvcc_detected) > 0:
        context["selected_cuda_home"] = str(aligned_env.get("CUDA_HOME") or "")
        context["auto_install_result"] = "not_needed"
        return aligned_env, context

    candidates = _discover_cuda_homes(
        torch_cuda=torch_cuda,
        profile_env=profile_env,
        search_paths=search_paths,
        venv_python=venv_python,
    )
    selected_home, selected_version, attempted = _select_matching_cuda_home(
        torch_cuda=torch_cuda,
        candidates=candidates,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    context["cuda_home_candidates"] = attempted
    if selected_home is not None:
        aligned_env = _apply_cuda_home_env(aligned_env, selected_home)
        context["selected_cuda_home"] = str(selected_home)
        context["nvcc_detected"] = selected_version or nvcc_detected
        context["auto_install_result"] = "selected_existing"
        return aligned_env, context

    if not auto_install_nvcc:
        context["auto_install_result"] = "disabled"
        raise RuntimeError(
            "PROFILE_UNSATISFIED: torch cuda version does not match available nvcc "
            "(auto install disabled). "
            f"{_format_cuda_alignment_context(context)}"
        )

    parsed = _parse_cuda_version(torch_cuda)
    if parsed is None:
        context["auto_install_result"] = "invalid_torch_cuda"
        raise RuntimeError(
            "PROFILE_UNSATISFIED: invalid torch cuda version during toolchain align "
            f"{_format_cuda_alignment_context(context)}"
        )

    pkg = f"nvidia-cuda-nvcc-cu{parsed[0]}"
    context["auto_install_attempted"] = True
    install = _run_command(
        command=[
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_python),
            pkg,
        ],
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    if int(install.returncode or 0) != 0:
        context["auto_install_result"] = f"failed(stderr={_tail(install.stderr)})"
        raise RuntimeError(
            "PROFILE_UNSATISFIED: failed to auto install nvcc package "
            f"package={pkg} {_format_cuda_alignment_context(context)}"
        )

    # 自动安装后重新发现候选并二次选择。
    candidates = _discover_cuda_homes(
        torch_cuda=torch_cuda,
        profile_env=profile_env,
        search_paths=search_paths,
        venv_python=venv_python,
    )
    selected_home, selected_version, attempted = _select_matching_cuda_home(
        torch_cuda=torch_cuda,
        candidates=candidates,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    context["cuda_home_candidates"] = attempted
    if selected_home is None:
        context["auto_install_result"] = "installed_but_not_matched"
        raise RuntimeError(
            "PROFILE_UNSATISFIED: auto installed nvcc package but still no matched cuda home "
            f"package={pkg} {_format_cuda_alignment_context(context)}"
        )

    aligned_env = _apply_cuda_home_env(aligned_env, selected_home)
    context["selected_cuda_home"] = str(selected_home)
    context["nvcc_detected"] = selected_version or context.get("nvcc_detected") or ""
    context["auto_install_result"] = "installed_and_selected"
    return aligned_env, context


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
            "--reinstall-package",
            "onedl-mmcv",
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
    profile_env: dict[str, str] | None = None,
    is_cuda_profile: bool = False,
    cuda_toolchain_auto_align: bool = True,
    cuda_toolchain_auto_install_nvcc: bool = True,
    cuda_toolchain_align_timeout_sec: int = 300,
    cuda_toolchain_search_paths: list[Path] | None = None,
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

    aligned_env = dict(env)
    cuda_context: dict[str, Any] = {
        "torch_cuda": "",
        "torch_version": "",
        "nvcc_detected": "",
        "cuda_home_candidates": [],
        "selected_cuda_home": "",
        "auto_install_attempted": False,
        "auto_install_result": "skipped",
    }
    if bool(is_cuda_profile) and bool(cuda_toolchain_auto_align):
        try:
            aligned_env, cuda_context = _ensure_cuda_toolchain(
                plugin_dir=plugin_dir,
                venv_python=venv_python,
                env=aligned_env,
                profile_env=profile_env,
                auto_install_nvcc=bool(cuda_toolchain_auto_install_nvcc),
                timeout_sec=max(30, int(cuda_toolchain_align_timeout_sec)),
                search_paths=list(cuda_toolchain_search_paths or [Path("/usr/local"), Path("/opt")]),
            )
        except Exception as exc:
            raise RuntimeError(
                "PROFILE_UNSATISFIED: failed to align CUDA toolchain before extension rebuild "
                f"reason={exc}"
            ) from exc

    has_mmcv, has_mmcv_ext = _probe_mmcv_ext(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    if (not has_mmcv) or has_mmcv_ext:
        return

    if not bool(mm_ext_auto_repair):
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext after uv sync; "
            "auto repair is disabled, set PLUGIN_MM_EXT_AUTO_REPAIR=true or rebuild onedl-mmcv manually. "
            f"{_format_cuda_alignment_context(cuda_context)}"
        )

    bootstrap_stderr = ""
    rebuild_stderr = ""
    try:
        bootstrap_stderr, rebuild_stderr = _repair_mmcv_ext(
            plugin_dir=plugin_dir,
            venv_python=venv_python,
            timeout_sec=max(60, int(mm_ext_auto_repair_timeout_sec)),
            env=aligned_env,
        )
    except Exception as exc:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext and auto repair failed "
            "(attempted rebuild with --no-build-isolation). "
            f"{_format_cuda_alignment_context(cuda_context)} "
            f"reason={exc}"
        ) from exc

    _, repaired_has_ext = _probe_mmcv_ext(
        venv_python=venv_python,
        cwd=plugin_dir,
        timeout_sec=timeout_sec,
        env=aligned_env,
    )
    if not repaired_has_ext:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: missing mmcv._ext after auto repair attempt; "
            f"{_format_cuda_alignment_context(cuda_context)} "
            f"bootstrap_stderr={bootstrap_stderr!r} rebuild_stderr={rebuild_stderr!r}"
        )
