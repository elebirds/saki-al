"""Loop lifecycle command mixin for runtime job service."""

from __future__ import annotations

import math
import uuid
from typing import List

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.api.branch import BranchCreate
from saki_api.modules.runtime.api.job import (
    LoopCreateData,
    LoopCreateRequest,
    LoopPatch,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.modules.runtime.domain import phase_for_mode
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import LoopMode, LoopStatus, LoopPhase


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

        normalized_global_config = self._normalize_loop_global_config(payload.global_config)
        normalized_global_config = self._merge_model_request_config(
            normalized_global_config,
            payload.model_request_config,
        )
        normalized_simulation = await self._resolve_simulation_config(
            simulation_config=payload.simulation_config,
            include_fields=set(payload.simulation_config.model_fields_set)
            if "simulation_config" in payload.model_fields_set
            else set(),
        )
        normalized_global_config["simulation"] = normalized_simulation.model_dump(mode="json", exclude_none=True)

        if payload.mode == LoopMode.SIMULATION and normalized_simulation.oracle_commit_id is None:
            raise BadRequestAppException("simulation mode requires oracle_commit_id")

        resolved_max_rounds = payload.max_rounds
        if payload.mode == LoopMode.MANUAL:
            resolved_max_rounds = 1

        create_data = LoopCreateData(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            mode=payload.mode,
            phase=phase_for_mode(payload.mode),
            phase_meta={},
            query_strategy=payload.query_strategy,
            model_arch=payload.model_arch,
            experiment_group_id=payload.experiment_group_id,
            global_config=normalized_global_config,
            current_iteration=0,
            status=payload.status,
            max_rounds=resolved_max_rounds,
            query_batch_size=payload.query_batch_size,
            min_seed_labeled=payload.min_seed_labeled,
            min_new_labels_per_round=payload.min_new_labels_per_round,
            stop_patience_rounds=payload.stop_patience_rounds,
            stop_min_gain=payload.stop_min_gain,
            auto_register_model=payload.auto_register_model,
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
        if payload.query_strategy is not None:
            patch.query_strategy = payload.query_strategy
        if payload.model_arch is not None:
            await self._validate_plugin_id(payload.model_arch)
            patch.model_arch = payload.model_arch
        if payload.experiment_group_id is not None:
            patch.experiment_group_id = payload.experiment_group_id

        if payload.max_rounds is not None:
            patch.max_rounds = payload.max_rounds
        if payload.query_batch_size is not None:
            patch.query_batch_size = payload.query_batch_size
        if payload.min_seed_labeled is not None:
            patch.min_seed_labeled = payload.min_seed_labeled
        if payload.min_new_labels_per_round is not None:
            patch.min_new_labels_per_round = payload.min_new_labels_per_round
        if payload.stop_patience_rounds is not None:
            patch.stop_patience_rounds = payload.stop_patience_rounds
        if payload.stop_min_gain is not None:
            patch.stop_min_gain = payload.stop_min_gain
        if payload.auto_register_model is not None:
            patch.auto_register_model = payload.auto_register_model

        next_mode = payload.mode if payload.mode is not None else loop.mode
        if payload.mode is not None:
            patch.mode = payload.mode
            patch.phase = phase_for_mode(payload.mode)

        resolved_global_config = loop.global_config
        if payload.global_config is not None:
            resolved_global_config = self._normalize_loop_global_config(payload.global_config)
        if payload.model_request_config is not None:
            resolved_global_config = self._merge_model_request_config(
                resolved_global_config,
                payload.model_request_config,
            )
        if payload.simulation_config is not None:
            resolved_global_config = dict(resolved_global_config or {})
            resolved_simulation = await self._resolve_simulation_config(
                simulation_config=payload.simulation_config,
                include_fields=set(payload.simulation_config.model_fields_set),
            )
            resolved_global_config["simulation"] = resolved_simulation.model_dump(mode="json", exclude_none=True)
        if (
            payload.global_config is not None
            or payload.model_request_config is not None
            or payload.simulation_config is not None
        ):
            patch.global_config = resolved_global_config

        if next_mode == LoopMode.SIMULATION:
            simulation_config = self._extract_simulation_config(resolved_global_config or {})
            if simulation_config.oracle_commit_id is None:
                raise BadRequestAppException("simulation mode requires oracle_commit_id")
        if next_mode == LoopMode.MANUAL:
            patch.max_rounds = 1

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

        group_id = uuid.uuid4()
        simulation_config = await self._resolve_simulation_config(
            simulation_config=payload.simulation_config,
            include_fields=set(payload.simulation_config.model_fields_set),
        )

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

        experiment_name = str(payload.experiment_name or f"sim-{str(group_id)[:8]}").strip()
        group_token = str(group_id).split("-")[0]

        loops: list[Loop] = []
        for strategy in strategies:
            for seed in simulation_config.seeds:
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

                loop_global_config = dict(payload.global_config or {})
                loop_global_config["simulation"] = simulation_config.model_copy(
                    update={"single_seed": seed}
                ).model_dump(mode="json", exclude_none=True)
                loop_payload = LoopCreateRequest(
                    name=self._truncate(f"{experiment_name}-{strategy}-seed-{seed}", max_len=100),
                    branch_id=fork_branch.id,
                    mode=LoopMode.SIMULATION,
                    query_strategy=strategy,
                    model_arch=payload.model_arch,
                    global_config=loop_global_config,
                    model_request_config=payload.model_request_config,
                    simulation_config=payload.simulation_config,
                    experiment_group_id=group_id,
                    status=payload.status,
                    max_rounds=simulation_config.max_rounds,
                    query_batch_size=max(1, int(math.ceil(simulation_config.step_ratio * 1000))),
                )
                loop = await self.create_loop(project_id=project_id, payload=loop_payload)
                loops.append(loop)

        return group_id, loops

    @transactional
    async def confirm_loop_step(self, loop_id: uuid.UUID) -> Loop:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != LoopMode.MANUAL:
            raise BadRequestAppException("confirm is only available in manual mode")
        if loop.phase != LoopPhase.MANUAL_EVAL:
            raise BadRequestAppException("loop is not waiting for manual confirmation")

        return await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(phase=LoopPhase.MANUAL_FINALIZE).model_dump(exclude_none=True),
        )

    @transactional
    async def start_loop(self, loop_id: uuid.UUID) -> Loop:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.status == LoopStatus.COMPLETED:
            raise BadRequestAppException("Completed loop cannot be started")
        return await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(status=LoopStatus.RUNNING).model_dump(exclude_none=True),
        )

    @transactional
    async def pause_loop(self, loop_id: uuid.UUID) -> Loop:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        return await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(status=LoopStatus.PAUSED).model_dump(exclude_none=True),
        )

    @transactional
    async def resume_loop(self, loop_id: uuid.UUID) -> Loop:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.status in {LoopStatus.STOPPED, LoopStatus.COMPLETED}:
            raise BadRequestAppException(f"Loop in status {loop.status} cannot be resumed")
        return await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(status=LoopStatus.RUNNING).model_dump(exclude_none=True),
        )

    @transactional
    async def stop_loop(self, loop_id: uuid.UUID) -> Loop:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        return await self.loop_repo.update_or_raise(
            loop_id,
            LoopPatch(status=LoopStatus.STOPPED).model_dump(exclude_none=True),
        )
