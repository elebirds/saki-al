from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from saki_plugin_sdk import RuntimeCapabilitySnapshot


def _safe_cuda_backend(torch_mod: Any, errors: list[str], details: dict[str, Any]) -> bool:
    try:
        cuda_mod = getattr(torch_mod, "cuda", None)
        if cuda_mod is None or not bool(cuda_mod.is_available()):
            return False
        count = int(cuda_mod.device_count() or 0)
        details["cuda_device_count"] = max(0, count)
        return count > 0
    except Exception as exc:  # pragma: no cover
        errors.append(f"cuda probe failed: {exc}")
        return False


def _ensure_mm_runtime_dependencies() -> None:
    """在 probing 阶段前置检查 MM 依赖，避免训练阶段才崩溃。"""
    try:
        importlib.import_module("mmengine")
    except Exception as exc:
        raise RuntimeError(
            f"runtime dependency check failed: missing mmengine ({exc.__class__.__name__}: {exc})"
        ) from exc

    mmcv_spec = importlib.util.find_spec("mmcv")
    if mmcv_spec is None:
        raise RuntimeError("runtime dependency check failed: missing mmcv package")

    mmcv_ext_spec = importlib.util.find_spec("mmcv._ext")
    if mmcv_ext_spec is None:
        raise RuntimeError(
            "runtime dependency check failed: missing mmcv._ext; "
            "please rebuild profile environment with a prebuilt onedl-mmcv wheel that contains mmcv._ext"
        )

    try:
        importlib.import_module("mmdet")
    except Exception as exc:
        raise RuntimeError(
            f"runtime dependency check failed: missing mmdet ({exc.__class__.__name__}: {exc})"
        ) from exc

    try:
        importlib.import_module("mmrotate")
    except Exception as exc:
        raise RuntimeError(
            f"runtime dependency check failed: missing mmrotate ({exc.__class__.__name__}: {exc})"
        ) from exc


def probe_torch_runtime_capability() -> RuntimeCapabilitySnapshot:
    errors: list[str] = []
    details: dict[str, Any] = {}

    try:
        import torch  # type: ignore
    except Exception as exc:
        return RuntimeCapabilitySnapshot(
            framework="torch",
            framework_version="",
            backends=["cpu"],
            backend_details={},
            errors=[f"torch import failed: {exc}"],
        )

    version = str(getattr(torch, "__version__", "") or "").strip()
    backends = ["cpu"]
    if _safe_cuda_backend(torch, errors, details):
        backends.append("cuda")

    # 关键设计：探测阶段就验证 MM 运行时完整性，减少“运行中失败”的排障成本。
    _ensure_mm_runtime_dependencies()

    return RuntimeCapabilitySnapshot(
        framework="torch",
        framework_version=version,
        backends=backends,
        backend_details=details,
        errors=errors,
    )
