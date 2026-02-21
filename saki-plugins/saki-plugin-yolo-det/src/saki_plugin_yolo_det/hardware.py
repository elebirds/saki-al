"""Hardware probing utilities for device resolution.

Copied from saki_executor.hardware.probe to avoid coupling plugins
to the executor package.  Only uses ``import torch`` lazily so the
module itself is free of heavy dependencies.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


ACCELERATOR_PRIORITY: tuple[str, ...] = ("cuda", "mps", "cpu")


def normalize_accelerator_name(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"cpu", "cuda", "mps", "auto"}:
        return raw
    if not raw:
        return ""
    if raw.startswith("cuda:"):
        return "cuda"
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    if parts and all(part.isdigit() for part in parts):
        return "cuda"
    if raw.isdigit():
        return "cuda"
    return ""


def _probe_cuda(torch_mod: Any) -> dict[str, Any]:
    available = False
    device_count = 0
    device_ids: list[str] = []
    try:
        cuda_mod = getattr(torch_mod, "cuda", None)
        available = bool(cuda_mod and cuda_mod.is_available())
        if available and cuda_mod:
            device_count = int(cuda_mod.device_count() or 0)
            device_ids = [str(idx) for idx in range(device_count)]
    except Exception:
        available = False
        device_count = 0
        device_ids = []
    return {
        "type": "cuda",
        "available": available and device_count > 0,
        "device_count": device_count if available else 0,
        "device_ids": device_ids if available else [],
    }


def _probe_mps(torch_mod: Any) -> dict[str, Any]:
    available = False
    try:
        backends = getattr(torch_mod, "backends", None)
        mps_mod = getattr(backends, "mps", None)
        available = bool(mps_mod and mps_mod.is_available())
    except Exception:
        available = False
    return {
        "type": "mps",
        "available": available,
        "device_count": 1 if available else 0,
        "device_ids": ["mps"] if available else [],
    }


def _probe_cpu() -> dict[str, Any]:
    return {
        "type": "cpu",
        "available": True,
        "device_count": 1,
        "device_ids": ["cpu"],
    }


def probe_hardware(*, cpu_workers: int | None = None, memory_mb: int | None = None) -> dict[str, Any]:
    try:
        import torch  # type: ignore
    except Exception:
        torch = None  # type: ignore

    cuda = _probe_cuda(torch) if torch is not None else {
        "type": "cuda",
        "available": False,
        "device_count": 0,
        "device_ids": [],
    }
    mps = _probe_mps(torch) if torch is not None else {
        "type": "mps",
        "available": False,
        "device_count": 0,
        "device_ids": [],
    }
    cpu = _probe_cpu()

    accelerators = [cuda, mps, cpu]
    gpu_count = int(cuda.get("device_count") or 0) if bool(cuda.get("available")) else 0
    gpu_device_ids = [int(v) for v in (cuda.get("device_ids") or []) if str(v).isdigit()]

    return {
        "gpu_count": gpu_count,
        "gpu_device_ids": gpu_device_ids,
        "cpu_workers": int(cpu_workers or (os.cpu_count() or 1)),
        "memory_mb": int(memory_mb or 0),
        "accelerators": accelerators,
    }


def available_accelerators(resource_payload: Mapping[str, Any] | None) -> set[str]:
    payload = resource_payload or {}
    available: set[str] = set()
    raw = payload.get("accelerators")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            accelerator = normalize_accelerator_name(item.get("type"))
            if accelerator and accelerator != "auto" and bool(item.get("available")):
                available.add(accelerator)
    if not available:
        if int(payload.get("gpu_count") or 0) > 0:
            available.add("cuda")
        available.add("cpu")
    return available
