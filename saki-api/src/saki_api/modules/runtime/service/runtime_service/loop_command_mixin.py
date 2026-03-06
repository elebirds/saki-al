"""Loop lifecycle command mixin for runtime service."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.api.round_step import (
    LoopCreateData,
    LoopCreateRequest,
    LoopPatch,
    LoopUpdateRequest,
)
from saki_api.modules.runtime.domain import phase_for_mode
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import LoopLifecycle, LoopMode


class LoopCommandMixin:
    @staticmethod
    def _extract_config_deterministic_level(config: dict[str, Any] | None) -> str:
        reproducibility = (config or {}).get("reproducibility")
        reproducibility_map = reproducibility if isinstance(reproducibility, dict) else {}
        return str(reproducibility_map.get("deterministic_level") or "off").strip().lower() or "off"

    def _extract_config_oracle_commit_id(self, config: dict[str, Any] | None) -> uuid.UUID | None:
        simulation = self._extract_simulation_config(dict(config or {}))
        raw = str(simulation.oracle_commit_id or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except Exception as exc:
            raise BadRequestAppException("config.mode.oracle_commit_id must be a valid UUID") from exc

    def _extract_config_snapshot_init(self, config: dict[str, Any] | None) -> dict[str, Any]:
        simulation = self._extract_simulation_config(dict(config or {}))
        snapshot_init = simulation.snapshot_init
        return {
            "train_seed_ratio": float(snapshot_init.train_seed_ratio),
            "val_ratio": float(snapshot_init.val_ratio),
            "test_ratio": float(snapshot_init.test_ratio),
            "val_policy": str(snapshot_init.val_policy or "").strip() or "anchor_only",
        }

    def _extract_config_finalize_train(self, config: dict[str, Any] | None) -> bool:
        simulation = self._extract_simulation_config(dict(config or {}))
        return bool(simulation.finalize_train)

    async def _validate_simulation_oracle_commit(
        self,
        *,
        project_id: uuid.UUID,
        mode: LoopMode,
        config: dict[str, Any] | None,
    ) -> uuid.UUID | None:
        if mode != LoopMode.SIMULATION:
            return None
        oracle_commit_id = self._extract_config_oracle_commit_id(config)
        if oracle_commit_id is None:
            raise BadRequestAppException("simulation mode requires config.mode.oracle_commit_id")
        oracle_commit = await self.project_gateway.get_commit(oracle_commit_id)
        if oracle_commit is None:
            raise BadRequestAppException("config.mode.oracle_commit_id does not exist")
        if oracle_commit.project_id != project_id:
            raise BadRequestAppException("config.mode.oracle_commit_id must belong to the same project")
        return oracle_commit_id

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
        await self._validate_simulation_oracle_commit(
            project_id=project_id,
            mode=payload.mode,
            config=normalized_config,
        )

        # Inject project's enabled_annotation_types into the plugin config
        # section so it flows through dispatcher → executor → plugin for
        # conditional logic (e.g. detect vs obb in YOLO plugin).
        project = await self.project_gateway.get_project(project_id)
        if project and getattr(project, "enabled_annotation_types", None):
            annotation_types = [
                str(t.value if hasattr(t, "value") else t)
                for t in project.enabled_annotation_types
            ]
            plugin_section = normalized_config.get("plugin")
            if isinstance(plugin_section, dict):
                plugin_section["annotation_types"] = annotation_types

        max_rounds = self._derive_loop_max_rounds(mode=mode_text, config=normalized_config)
        query_batch_size = self._derive_query_batch_size(mode=mode_text, config=normalized_config)

        create_data = LoopCreateData(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            mode=payload.mode,
            phase=phase_for_mode(payload.mode),
            model_arch=payload.model_arch,
            config=normalized_config,
            current_iteration=0,
            lifecycle=payload.lifecycle,
            max_rounds=max_rounds,
            query_batch_size=query_batch_size,
            min_new_labels_per_round=120,
            active_snapshot_version_id=None,
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
        if payload.lifecycle is not None:
            patch.lifecycle = payload.lifecycle

        next_mode = payload.mode if payload.mode is not None else loop.mode
        if payload.mode is not None:
            patch.mode = payload.mode
            patch.phase = phase_for_mode(payload.mode)

        if payload.config is not None or payload.mode is not None:
            mode_text = str(next_mode.value if hasattr(next_mode, "value") else next_mode)
            raw_config = payload.config if payload.config is not None else (loop.config or {})
            normalized_config = self._normalize_loop_config(raw_config, mode=mode_text)
            next_seed = self._get_loop_global_seed(normalized_config)
            current_seed = self._get_loop_global_seed(loop.config or {})
            if (
                str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
                != "draft"
                and current_seed != next_seed
            ):
                raise BadRequestAppException("config.reproducibility.global_seed is immutable once lifecycle is not draft")
            current_deterministic_level = self._extract_config_deterministic_level(loop.config or {})
            next_deterministic_level = self._extract_config_deterministic_level(normalized_config)
            if (
                str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
                != "draft"
                and current_deterministic_level != next_deterministic_level
            ):
                raise BadRequestAppException(
                    "config.reproducibility.deterministic_level is immutable once lifecycle is not draft"
                )
            current_finalize_train = (
                self._extract_config_finalize_train(loop.config or {})
                if loop.mode == LoopMode.SIMULATION
                else True
            )
            next_finalize_train = (
                self._extract_config_finalize_train(normalized_config)
                if next_mode == LoopMode.SIMULATION
                else True
            )
            if (
                str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
                != "draft"
                and current_finalize_train != next_finalize_train
            ):
                raise BadRequestAppException(
                    "config.mode.finalize_train is immutable once lifecycle is not draft"
                )

            current_oracle_commit_id = await self._validate_simulation_oracle_commit(
                project_id=loop.project_id,
                mode=loop.mode,
                config=loop.config or {},
            )
            next_oracle_commit_id = await self._validate_simulation_oracle_commit(
                project_id=loop.project_id,
                mode=next_mode,
                config=normalized_config,
            )
            current_snapshot_init = self._extract_config_snapshot_init(loop.config or {})
            next_snapshot_init = self._extract_config_snapshot_init(normalized_config)
            if current_oracle_commit_id != next_oracle_commit_id or current_snapshot_init != next_snapshot_init:
                can_update_oracle = (
                    loop.lifecycle == LoopLifecycle.DRAFT and loop.active_snapshot_version_id is None
                )
                if not can_update_oracle:
                    raise BadRequestAppException(
                        "config.mode.oracle_commit_id/config.mode.snapshot_init can only change "
                        "while loop is draft and snapshot is not initialized"
                    )
            patch.config = normalized_config
            patch.max_rounds = self._derive_loop_max_rounds(mode=mode_text, config=normalized_config)
            patch.query_batch_size = self._derive_query_batch_size(mode=mode_text, config=normalized_config)

        patch_payload = patch.model_dump(exclude_none=True)
        if not patch_payload:
            return loop
        return await self.loop_repo.update_or_raise(loop_id, patch_payload)
