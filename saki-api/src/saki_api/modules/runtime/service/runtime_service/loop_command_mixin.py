"""Loop lifecycle command mixin for runtime service."""

from __future__ import annotations

import uuid
from typing import List

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.api.branch import BranchCreate
from saki_api.modules.runtime.api.round_step import (
    LoopCreateData,
    LoopCreateRequest,
    LoopPatch,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.modules.runtime.domain import phase_for_mode
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import LoopMode


class LoopCommandMixin:
    @transactional
    async def create_loop(self, project_id: uuid.UUID, payload: LoopCreateRequest) -> Loop:
        branch = await self.project_gateway.get_branch(payload.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {payload.branch_id} not found")
        if branch.project_id != project_id:
            raise BadRequestAppException("Branch does not belong to this project")

        await self._validate_plugin_id(payload.model_arch)
        existing = await self.loop_repo.get_one(filters=[Loop.branch_id == payload.branch_id])
        if existing:
            raise BadRequestAppException("Branch already has a loop bound")

        mode_text = str(payload.mode.value if hasattr(payload.mode, "value") else payload.mode)
        normalized_config = self._normalize_loop_config(payload.config, mode=mode_text)
        max_rounds = self._derive_loop_max_rounds(mode=mode_text, config=normalized_config)
        query_batch_size = self._derive_query_batch_size(mode=mode_text, config=normalized_config)

        create_data = LoopCreateData(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            mode=payload.mode,
            phase=phase_for_mode(payload.mode),
            phase_meta={},
            model_arch=payload.model_arch,
            experiment_group_id=payload.experiment_group_id,
            config=normalized_config,
            current_iteration=0,
            status=payload.status,
            max_rounds=max_rounds,
            query_batch_size=query_batch_size,
            min_seed_labeled=100,
            min_new_labels_per_round=120,
            stop_patience_rounds=2,
            stop_min_gain=0.002,
            auto_register_model=True,
        )
        return await self.loop_repo.create(create_data.model_dump(exclude_none=True))

    @transactional
    async def update_loop(self, loop_id: uuid.UUID, payload: LoopUpdateRequest) -> Loop:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        patch = LoopPatch()

        if payload.name is not None:
            patch.name = payload.name
        if payload.model_arch is not None:
            await self._validate_plugin_id(payload.model_arch)
            patch.model_arch = payload.model_arch
        if payload.experiment_group_id is not None:
            patch.experiment_group_id = payload.experiment_group_id
        if payload.status is not None:
            patch.status = payload.status

        next_mode = payload.mode if payload.mode is not None else loop.mode
        if payload.mode is not None:
            patch.mode = payload.mode
            patch.phase = phase_for_mode(payload.mode)

        if payload.config is not None or payload.mode is not None:
            mode_text = str(next_mode.value if hasattr(next_mode, "value") else next_mode)
            raw_config = payload.config if payload.config is not None else (loop.config or {})
            normalized_config = self._normalize_loop_config(raw_config, mode=mode_text)
            patch.config = normalized_config
            patch.max_rounds = self._derive_loop_max_rounds(mode=mode_text, config=normalized_config)
            patch.query_batch_size = self._derive_query_batch_size(mode=mode_text, config=normalized_config)

        patch_payload = patch.model_dump(exclude_none=True)
        if not patch_payload:
            return loop
        return await self.loop_repo.update_or_raise(loop_id, patch_payload)

    @transactional
    async def create_simulation_experiment(
        self,
        *,
        project_id: uuid.UUID,
        payload: SimulationExperimentCreateRequest,
    ) -> tuple[uuid.UUID, List[Loop]]:
        branch = await self.project_gateway.get_branch(payload.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {payload.branch_id} not found")
        if branch.project_id != project_id:
            raise BadRequestAppException("Branch does not belong to this project")
        await self._validate_plugin_id(payload.model_arch)

        strategies: list[str] = []
        for raw in payload.strategies:
            key = str(raw or "").strip()
            if not key or key in strategies:
                continue
            strategies.append(key)
        if self.RANDOM_BASELINE_STRATEGY not in strategies:
            strategies.insert(0, self.RANDOM_BASELINE_STRATEGY)
        if not strategies:
            raise BadRequestAppException("strategies must contain at least one item")

        base_config = self._normalize_loop_config(payload.config, mode=LoopMode.SIMULATION.value)
        mode_config = base_config.get("mode") if isinstance(base_config.get("mode"), dict) else {}
        seeds_raw = mode_config.get("seeds") if isinstance(mode_config, dict) else None
        seeds: list[int] = []
        for item in seeds_raw or [0, 1, 2, 3, 4]:
            try:
                seeds.append(int(item))
            except Exception:
                continue
        if not seeds:
            seeds = [0, 1, 2, 3, 4]

        group_id = uuid.uuid4()
        experiment_name = str(payload.experiment_name or f"sim-{str(group_id)[:8]}").strip()
        group_token = str(group_id).split("-")[0]

        loops: list[Loop] = []
        for strategy in strategies:
            for seed in seeds:
                strategy_segment = self._normalize_branch_segment(strategy, fallback="strategy")
                branch_name = await self._next_available_branch_name(
                    project_id=project_id,
                    base_name=f"simulation/{group_token}/{strategy_segment}/seed-{seed}",
                )
                fork_branch = await self.project_gateway.create_branch(
                    BranchCreate(
                        project_id=project_id,
                        name=branch_name,
                        head_commit_id=branch.head_commit_id,
                        description=self._truncate(
                            f"[simulation] {experiment_name} · {strategy} · seed={seed}",
                            max_len=500,
                        ),
                        is_protected=False,
                    )
                )

                config = dict(base_config)
                sampling_cfg = dict(config.get("sampling") or {})
                sampling_cfg["strategy"] = strategy
                config["sampling"] = sampling_cfg
                mode_cfg = dict(config.get("mode") or {})
                mode_cfg["single_seed"] = seed
                config["mode"] = mode_cfg

                loop_payload = LoopCreateRequest(
                    name=self._truncate(f"{experiment_name}-{strategy}-seed-{seed}", max_len=100),
                    branch_id=fork_branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch=payload.model_arch,
                    config=config,
                    experiment_group_id=group_id,
                    status=payload.status,
                )
                loop = await self.create_loop(project_id=project_id, payload=loop_payload)
                loops.append(loop)

        return group_id, loops
