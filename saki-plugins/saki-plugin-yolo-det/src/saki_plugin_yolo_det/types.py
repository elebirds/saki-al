from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrainConfig:
    epochs: int
    batch: int
    imgsz: int
    patience: int
    device: Any
    requested_device: str
    resolved_backend: str
    resolved_base_model: str
    train_seed: int
    deterministic: bool
    yolo_task: str = "obb"


@dataclass(frozen=True)
class PreparedDataset:
    manifest: dict[str, Any]
    yolo_task: str = "obb"
