"""Simulation config helper mixin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SimulationModeConfig:
    oracle_commit_id: str | None = None
    seed_ratio: float = 0.05
    step_ratio: float = 0.05
    random_baseline_enabled: bool = True
    seeds: list[int] | None = None
    single_seed: int | None = None


class SimulationConfigMixin:
    @staticmethod
    def _extract_simulation_config(loop_config: dict[str, Any]) -> SimulationModeConfig:
        payload = loop_config.get("mode")
        mode_cfg = payload if isinstance(payload, dict) else {}
        seeds_raw = mode_cfg.get("seeds") or [0, 1, 2, 3, 4]
        seeds: list[int] = []
        for item in seeds_raw:
            try:
                seeds.append(int(item))
            except Exception:
                continue
        single_seed = None
        if mode_cfg.get("single_seed") is not None:
            try:
                single_seed = int(mode_cfg.get("single_seed"))
            except Exception:
                single_seed = None
        return SimulationModeConfig(
            oracle_commit_id=str(mode_cfg.get("oracle_commit_id") or "").strip() or None,
            seed_ratio=float(mode_cfg.get("seed_ratio", 0.05) or 0.05),
            step_ratio=float(mode_cfg.get("step_ratio", 0.05) or 0.05),
            random_baseline_enabled=bool(mode_cfg.get("random_baseline_enabled", True)),
            seeds=seeds or [0, 1, 2, 3, 4],
            single_seed=single_seed,
        )
