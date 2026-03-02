from __future__ import annotations

from typing import Any, Mapping

from saki_executor.runtime.capability.host_probe_service import HostProbeService
from saki_plugin_sdk import normalize_backend_name

__all__ = [
    "ACCELERATOR_PRIORITY",
    "available_accelerators",
    "normalize_backend_name",
    "normalize_accelerator_name",
    "probe_hardware",
]


ACCELERATOR_PRIORITY: tuple[str, ...] = ("cuda", "mps", "cpu")


def probe_hardware(*, cpu_workers: int | None = None, memory_mb: int | None = None) -> dict[str, Any]:
    service = HostProbeService()
    snapshot = service.probe(
        cpu_workers=max(1, int(cpu_workers or 1)),
        memory_mb=max(0, int(memory_mb or 0)),
    )
    return service.to_resource_payload(snapshot)


def available_accelerators(resource_payload: Mapping[str, Any] | None) -> set[str]:
    payload = resource_payload or {}
    rows = payload.get("accelerators")
    available: set[str] = {"cpu"}
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            backend = normalize_backend_name(item.get("type"))
            if backend and backend != "auto" and bool(item.get("available")):
                available.add(backend)
    return available


def normalize_accelerator_name(value: Any) -> str:
    return normalize_backend_name(value)
