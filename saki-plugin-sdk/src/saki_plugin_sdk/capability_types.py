from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _normalize_backend(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"cpu", "cuda", "mps"}:
        return raw
    return ""


@dataclass(frozen=True)
class GpuDeviceCapability:
    id: str
    name: str = ""
    memory_mb: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "memory_mb": int(self.memory_mb),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GpuDeviceCapability":
        return cls(
            id=str(payload.get("id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            memory_mb=max(0, int(payload.get("memory_mb") or 0)),
        )


@dataclass(frozen=True)
class HostCapabilitySnapshot:
    cpu_workers: int
    memory_mb: int
    gpus: list[GpuDeviceCapability] = field(default_factory=list)
    metal_available: bool = False
    platform: str = ""
    arch: str = ""
    driver_info: dict[str, Any] = field(default_factory=dict)

    def available_backends(self) -> set[str]:
        backends = {"cpu"}
        if self.gpus:
            backends.add("cuda")
        if self.metal_available:
            backends.add("mps")
        return backends

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_workers": int(self.cpu_workers),
            "memory_mb": int(self.memory_mb),
            "gpus": [item.to_dict() for item in self.gpus],
            "metal_available": bool(self.metal_available),
            "platform": self.platform,
            "arch": self.arch,
            "driver_info": dict(self.driver_info),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HostCapabilitySnapshot":
        rows = payload.get("gpus")
        gpus = [
            GpuDeviceCapability.from_dict(item)
            for item in (rows if isinstance(rows, list) else [])
            if isinstance(item, dict)
        ]
        return cls(
            cpu_workers=max(1, int(payload.get("cpu_workers") or 1)),
            memory_mb=max(0, int(payload.get("memory_mb") or 0)),
            gpus=gpus,
            metal_available=bool(payload.get("metal_available")),
            platform=str(payload.get("platform") or "").strip().lower(),
            arch=str(payload.get("arch") or "").strip().lower(),
            driver_info=dict(payload.get("driver_info") or {}),
        )


@dataclass(frozen=True)
class RuntimeCapabilitySnapshot:
    framework: str
    framework_version: str
    backends: list[str] = field(default_factory=list)
    backend_details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def empty(
        cls,
        *,
        framework: str = "",
        error: str = "",
    ) -> "RuntimeCapabilitySnapshot":
        errors = [error] if error else []
        return cls(
            framework=str(framework or "").strip().lower(),
            framework_version="",
            backends=[],
            backend_details={},
            errors=errors,
        )

    def available_backends(self) -> set[str]:
        return {
            item
            for item in (_normalize_backend(value) for value in self.backends)
            if item
        } | {"cpu"}

    def to_dict(self) -> dict[str, Any]:
        normalized = []
        seen: set[str] = set()
        for value in self.backends:
            backend = _normalize_backend(value)
            if not backend or backend in seen:
                continue
            seen.add(backend)
            normalized.append(backend)
        return {
            "framework": str(self.framework or "").strip().lower(),
            "framework_version": str(self.framework_version or "").strip(),
            "backends": normalized,
            "backend_details": dict(self.backend_details or {}),
            "errors": [str(item) for item in self.errors if str(item).strip()],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeCapabilitySnapshot":
        rows = payload.get("backends")
        backends: list[str] = []
        seen: set[str] = set()
        for value in (rows if isinstance(rows, list) else []):
            backend = _normalize_backend(value)
            if not backend or backend in seen:
                continue
            seen.add(backend)
            backends.append(backend)
        errors_raw = payload.get("errors")
        errors = [str(item) for item in (errors_raw if isinstance(errors_raw, list) else []) if str(item).strip()]
        return cls(
            framework=str(payload.get("framework") or "").strip().lower(),
            framework_version=str(payload.get("framework_version") or "").strip(),
            backends=backends,
            backend_details=dict(payload.get("backend_details") or {}),
            errors=errors,
        )
