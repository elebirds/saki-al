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
    strong_deterministic: bool
    yolo_task: str = "obb"
    cache: bool = False
    workers: int = 2
    init_mode: str = "checkpoint_direct"
    arch_yaml_ref: str = ""
    requested_epochs: int = 0
    train_budget_mode: str = "fixed_epochs"
    target_updates: int = 0
    min_epochs: int = 1
    max_epochs: int = 1000
    budget_disable_early_stop: bool = True
    train_sample_count: int = 0
    steps_per_epoch: int = 0
    effective_epochs: int = 0
    effective_patience: int = 0


@dataclass(frozen=True)
class PreparedDataset:
    manifest: dict[str, Any]
    yolo_task: str = "obb"
