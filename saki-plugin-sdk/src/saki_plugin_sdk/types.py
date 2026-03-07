from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskRuntimeContext:
    task_id: str
    round_id: str
    round_index: int
    attempt: int
    task_type: str
    mode: str
    split_seed: int
    train_seed: int
    sampling_seed: int
    resolved_device_backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "round_id": self.round_id,
            "round_index": self.round_index,
            "attempt": self.attempt,
            "task_type": self.task_type,
            "mode": self.mode,
            "split_seed": self.split_seed,
            "train_seed": self.train_seed,
            "sampling_seed": self.sampling_seed,
            "resolved_device_backend": self.resolved_device_backend,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskRuntimeContext":
        if not isinstance(payload, dict):
            raise ValueError("runtime context must be an object")

        task_id = str(payload.get("task_id") or "").strip()
        task_type = str(payload.get("task_type") or "").strip().lower()
        mode = str(payload.get("mode") or "").strip().lower()
        if not task_id:
            raise ValueError("runtime context missing task_id")
        if not task_type:
            raise ValueError("runtime context missing task_type")
        if not mode:
            raise ValueError("runtime context missing mode")

        def _to_int(key: str, default: int) -> int:
            try:
                return int(payload.get(key, default))
            except Exception:
                return default

        return cls(
            task_id=task_id,
            round_id=str(payload.get("round_id") or "").strip(),
            round_index=max(0, _to_int("round_index", 0)),
            attempt=max(1, _to_int("attempt", 1)),
            task_type=task_type,
            mode=mode,
            split_seed=max(0, _to_int("split_seed", 0)),
            train_seed=max(0, _to_int("train_seed", 0)),
            sampling_seed=max(0, _to_int("sampling_seed", 0)),
            resolved_device_backend=str(payload.get("resolved_device_backend") or "").strip().lower(),
        )
