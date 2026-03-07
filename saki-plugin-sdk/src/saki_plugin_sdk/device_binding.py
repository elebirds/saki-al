from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceBinding:
    backend: str
    device_spec: str
    precision: str
    profile_id: str
    reason: str
    fallback_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": str(self.backend or "").strip().lower(),
            "device_spec": str(self.device_spec or "").strip(),
            "precision": str(self.precision or "").strip().lower(),
            "profile_id": str(self.profile_id or "").strip(),
            "reason": str(self.reason or "").strip(),
            "fallback_applied": bool(self.fallback_applied),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeviceBinding":
        return cls(
            backend=str(payload.get("backend") or "").strip().lower(),
            device_spec=str(payload.get("device_spec") or "").strip(),
            precision=str(payload.get("precision") or "").strip().lower(),
            profile_id=str(payload.get("profile_id") or "").strip(),
            reason=str(payload.get("reason") or "").strip(),
            fallback_applied=bool(payload.get("fallback_applied")),
        )
