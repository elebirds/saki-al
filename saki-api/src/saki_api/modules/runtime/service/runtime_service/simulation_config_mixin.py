"""Simulation config helper mixin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SimulationModeConfig:
    oracle_commit_id: str | None = None
    seed_ratio: float = 0.05
    step_ratio: float = 0.05


class SimulationConfigMixin:
    @staticmethod
    def _extract_simulation_config(loop_config: dict[str, Any]) -> SimulationModeConfig:
        payload = loop_config.get("mode")
        mode_cfg = payload if isinstance(payload, dict) else {}
        return SimulationModeConfig(
            oracle_commit_id=str(mode_cfg.get("oracle_commit_id") or "").strip() or None,
            seed_ratio=float(mode_cfg.get("seed_ratio", 0.05) or 0.05),
            step_ratio=float(mode_cfg.get("step_ratio", 0.05) or 0.05),
        )
