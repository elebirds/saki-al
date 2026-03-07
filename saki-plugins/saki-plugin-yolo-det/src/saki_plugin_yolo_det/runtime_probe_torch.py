from __future__ import annotations

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
    except Exception as exc:  # pragma: no cover - depends on runtime env
        errors.append(f"cuda probe failed: {exc}")
        return False


def _safe_mps_backend(torch_mod: Any, errors: list[str], details: dict[str, Any]) -> bool:
    try:
        backends_mod = getattr(torch_mod, "backends", None)
        mps_mod = getattr(backends_mod, "mps", None)
        if mps_mod is None:
            return False
        available = bool(mps_mod.is_available())
        details["mps_available"] = available
        return available
    except Exception as exc:  # pragma: no cover - depends on runtime env
        errors.append(f"mps probe failed: {exc}")
        return False


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

    framework_version = str(getattr(torch, "__version__", "") or "").strip()
    backends = ["cpu"]
    if _safe_cuda_backend(torch, errors, details):
        backends.append("cuda")
    if _safe_mps_backend(torch, errors, details):
        backends.append("mps")

    return RuntimeCapabilitySnapshot(
        framework="torch",
        framework_version=framework_version,
        backends=backends,
        backend_details=details,
        errors=errors,
    )
