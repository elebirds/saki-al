"""Simulation configuration and round progression mixin for runtime job service."""

from __future__ import annotations

import math
import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.runtime.api.job import LoopSimulationConfig
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase
from saki_api.modules.system.service.system_settings_reader import system_settings_reader


class SimulationConfigMixin:
    @staticmethod
    def _normalize_simulation_config(raw: dict[str, Any] | None) -> LoopSimulationConfig:
        payload = dict(raw or {})
        oracle_commit_id_raw = str(payload.get("oracle_commit_id") or "").strip()
        oracle_commit_id: uuid.UUID | None = None
        if oracle_commit_id_raw:
            try:
                oracle_commit_id = uuid.UUID(oracle_commit_id_raw)
            except Exception as exc:
                raise BadRequestAppException("invalid simulation oracle_commit_id") from exc

        seed_ratio = float(payload.get("seed_ratio", 0.05) or 0.05)
        step_ratio = float(payload.get("step_ratio", 0.05) or 0.05)
        max_rounds = max(1, int(payload.get("max_rounds", 20) or 20))
        seeds_raw = payload.get("seeds") or [0, 1, 2, 3, 4]
        seeds: list[int] = []
        for item in seeds_raw:
            try:
                seeds.append(int(item))
            except Exception:
                continue
        if not seeds:
            seeds = [0, 1, 2, 3, 4]

        parsed_single_seed: int | None = None
        if payload.get("single_seed") is not None:
            try:
                parsed_single_seed = int(payload.get("single_seed"))
            except Exception:
                parsed_single_seed = None

        return LoopSimulationConfig(
            oracle_commit_id=oracle_commit_id,
            seed_ratio=min(1.0, max(0.0, seed_ratio)),
            step_ratio=min(1.0, max(0.0, step_ratio)),
            max_rounds=max_rounds,
            random_baseline_enabled=bool(payload.get("random_baseline_enabled", True)),
            seeds=seeds,
            single_seed=parsed_single_seed,
        )

    @staticmethod
    def _extract_simulation_config(global_config: dict[str, Any]) -> LoopSimulationConfig:
        payload = global_config.get("simulation")
        if not isinstance(payload, dict):
            return SimulationConfigMixin._normalize_simulation_config({})
        return SimulationConfigMixin._normalize_simulation_config(payload)

    async def _get_system_simulation_defaults(self) -> dict[str, Any]:
        return await system_settings_reader.get_simulation_defaults()

    async def _resolve_simulation_config(
        self,
        *,
        simulation_config: LoopSimulationConfig,
        include_fields: set[str] | None = None,
    ) -> LoopSimulationConfig:
        defaults = await self._get_system_simulation_defaults()
        include = include_fields if include_fields is not None else None
        payload = simulation_config.model_dump(
            exclude_none=True,
            include=include,
        )
        return self._normalize_simulation_config({**defaults, **payload})

    async def _resolve_simulation_round(
        self,
        *,
        loop: Loop,
        next_round: int,
        source_commit_id: uuid.UUID | None,
        params: dict[str, Any],
    ) -> tuple[uuid.UUID | None, LoopPhase, dict[str, Any]]:
        if loop.mode != LoopMode.SIMULATION:
            if loop.mode == LoopMode.MANUAL:
                return source_commit_id, LoopPhase.MANUAL_TRAIN, dict(loop.phase_meta or {})
            return source_commit_id, LoopPhase.AL_TRAIN, dict(loop.phase_meta or {})

        simulation = LoopSimulationConfig.model_validate((loop.global_config or {}).get("simulation") or {})
        if simulation.oracle_commit_id is None:
            raise RuntimeError("simulation mode requires oracle_commit_id")

        oracle_commit_id = simulation.oracle_commit_id
        total_count = await self.annotation_gateway.count_samples_at_commit(oracle_commit_id)
        if total_count <= 0:
            raise RuntimeError("simulation oracle commit has no labeled samples")

        seed_ratio = float(simulation.seed_ratio or 0.05)
        step_ratio = float(simulation.step_ratio or 0.05)
        target_ratio = min(1.0, seed_ratio + (next_round - 1) * step_ratio)
        prev_ratio = float((loop.phase_meta or {}).get("current_ratio") or 0.0)
        prev_selected = int((loop.phase_meta or {}).get("selected_count") or max(1, math.ceil(seed_ratio * total_count)))
        target_total = max(prev_selected, int(math.ceil(target_ratio * total_count)))
        add_count = max(0, target_total - prev_selected)

        phase_meta = dict(loop.phase_meta or {})
        phase_meta.update(
            {
                "total_count": total_count,
                "current_ratio": target_ratio,
                "selected_count": target_total,
                "add_count": add_count,
                "prev_ratio": prev_ratio,
            }
        )

        params["simulation"] = {
            "oracle_commit_id": str(oracle_commit_id),
            "seed_ratio": seed_ratio,
            "step_ratio": step_ratio,
            "target_ratio": target_ratio,
            "total_count": total_count,
            "add_count": add_count,
            "single_seed": int(simulation.single_seed or 0),
        }
        return oracle_commit_id, LoopPhase.SIM_TRAIN, phase_meta
