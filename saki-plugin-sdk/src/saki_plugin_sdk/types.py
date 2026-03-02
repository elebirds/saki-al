from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepRuntimeContext:
    step_id: str
    round_id: str
    round_index: int
    attempt: int
    step_type: str
    mode: str
    split_seed: int
    train_seed: int
    sampling_seed: int
    resolved_device_backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "round_id": self.round_id,
            "round_index": self.round_index,
            "attempt": self.attempt,
            "step_type": self.step_type,
            "mode": self.mode,
            "split_seed": self.split_seed,
            "train_seed": self.train_seed,
            "sampling_seed": self.sampling_seed,
            "resolved_device_backend": self.resolved_device_backend,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StepRuntimeContext":
        if not isinstance(payload, dict):
            raise ValueError("runtime context must be an object")

        step_id = str(payload.get("step_id") or "").strip()
        step_type = str(payload.get("step_type") or "").strip().lower()
        mode = str(payload.get("mode") or "").strip().lower()
        if not step_id:
            raise ValueError("runtime context missing step_id")
        if not step_type:
            raise ValueError("runtime context missing step_type")
        if not mode:
            raise ValueError("runtime context missing mode")

        def _to_int(key: str, default: int) -> int:
            try:
                return int(payload.get(key, default))
            except Exception:
                return default

        return cls(
            step_id=step_id,
            round_id=str(payload.get("round_id") or "").strip(),
            round_index=max(0, _to_int("round_index", 0)),
            attempt=max(1, _to_int("attempt", 1)),
            step_type=step_type,
            mode=mode,
            split_seed=max(0, _to_int("split_seed", 0)),
            train_seed=max(0, _to_int("train_seed", 0)),
            sampling_seed=max(0, _to_int("sampling_seed", 0)),
            resolved_device_backend=str(payload.get("resolved_device_backend") or "").strip().lower(),
        )
