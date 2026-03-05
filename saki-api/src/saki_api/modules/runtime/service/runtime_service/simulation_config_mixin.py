"""Simulation config helper mixin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SimulationSnapshotInitConfig:
    train_seed_ratio: float = 0.05
    val_ratio: float = 0.1
    test_ratio: float = 0.1
    val_policy: str = "anchor_only"


@dataclass(slots=True)
class SimulationModeConfig:
    oracle_commit_id: str | None = None
    max_rounds: int = 20
    snapshot_init: SimulationSnapshotInitConfig = field(default_factory=SimulationSnapshotInitConfig)


class SimulationConfigMixin:
    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _extract_simulation_config(loop_config: dict[str, Any]) -> SimulationModeConfig:
        payload = loop_config.get("mode")
        mode_cfg = payload if isinstance(payload, dict) else {}
        snapshot_init_raw = mode_cfg.get("snapshot_init")
        snapshot_init_cfg = snapshot_init_raw if isinstance(snapshot_init_raw, dict) else {}
        return SimulationModeConfig(
            oracle_commit_id=str(mode_cfg.get("oracle_commit_id") or "").strip() or None,
            max_rounds=max(1, SimulationConfigMixin._safe_int(mode_cfg.get("max_rounds", 20), 20)),
            snapshot_init=SimulationSnapshotInitConfig(
                train_seed_ratio=SimulationConfigMixin._safe_float(snapshot_init_cfg.get("train_seed_ratio", 0.05), 0.05),
                val_ratio=SimulationConfigMixin._safe_float(snapshot_init_cfg.get("val_ratio", 0.1), 0.1),
                test_ratio=SimulationConfigMixin._safe_float(snapshot_init_cfg.get("test_ratio", 0.1), 0.1),
                val_policy=str(snapshot_init_cfg.get("val_policy") or "anchor_only").strip() or "anchor_only",
            ),
        )
