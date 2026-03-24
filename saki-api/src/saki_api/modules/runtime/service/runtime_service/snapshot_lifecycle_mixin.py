"""Snapshot lifecycle mixin."""

from __future__ import annotations

from collections import Counter
import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion
from saki_api.modules.shared.modeling.enums import (
    LoopMode,
    SnapshotPartition,
    SnapshotUpdateMode,
    SnapshotValPolicy,
    VisibilitySource,
)


class SnapshotLifecycleMixin:
    async def _get_branch_head_commit_id(self, branch_id: uuid.UUID) -> uuid.UUID | None:
        return await self.project_gateway.get_branch_head_commit_id(branch_id)

    async def _list_project_sample_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        return await self.project_gateway.list_project_sample_ids(project_id)

    async def _list_snapshot_sample_records(self, *, sample_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        unique_sample_ids = self._dedupe_uuid_list(sample_ids)
        if not unique_sample_ids:
            return []
        samples = await self.snapshot_query_repo.list_samples_by_ids(sample_ids=unique_sample_ids)
        sample_map = {sample.id: sample for sample in samples}
        records: list[dict[str, Any]] = []
        for sample_id in unique_sample_ids:
            sample = sample_map.get(sample_id)
            if sample is None:
                records.append({"sample_id": sample_id, "name": "", "meta_info": {}})
                continue
            records.append(
                {
                    "sample_id": sample.id,
                    "name": str(sample.name or ""),
                    "meta_info": dict(sample.meta_info or {}),
                }
            )
        return records

    async def _resolve_simulation_oracle_commit_id(self, *, loop: Any) -> uuid.UUID:
        if loop.mode != LoopMode.SIMULATION:
            raise BadRequestAppException("oracle commit is only available for simulation loop")

        config = loop.config if isinstance(loop.config, dict) else {}
        simulation = self._extract_simulation_config(config)
        raw_oracle_commit_id = str(simulation.oracle_commit_id or "").strip()
        if not raw_oracle_commit_id:
            raise BadRequestAppException("simulation mode requires config.mode.oracle_commit_id")
        try:
            oracle_commit_id = uuid.UUID(raw_oracle_commit_id)
        except Exception as exc:
            raise BadRequestAppException("config.mode.oracle_commit_id must be a valid UUID") from exc

        oracle_commit = await self.project_gateway.get_commit(oracle_commit_id)
        if oracle_commit is None:
            raise BadRequestAppException("config.mode.oracle_commit_id does not exist")
        if oracle_commit.project_id != loop.project_id:
            raise BadRequestAppException("config.mode.oracle_commit_id must belong to the same project")
        return oracle_commit_id

    async def _list_labeled_sample_ids_at_commit(self, *, commit_id: uuid.UUID) -> list[uuid.UUID]:
        return await self.annotation_gateway.list_labeled_sample_ids_at_commit(commit_id=commit_id)

    async def _resolve_reveal_source_commit_id(self, *, loop: Any) -> uuid.UUID | None:
        if loop.mode == LoopMode.SIMULATION:
            return await self._resolve_simulation_oracle_commit_id(loop=loop)
        return await self._get_branch_head_commit_id(loop.branch_id)

    async def _get_active_snapshot_or_raise(self, loop_id: uuid.UUID) -> tuple[Any, ALSnapshotVersion]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode not in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION}:
            raise BadRequestAppException("snapshot is only available for active_learning/simulation loop")
        if not loop.active_snapshot_version_id:
            raise BadRequestAppException("loop has no active snapshot")
        snapshot = await self.al_snapshot_version_repo.get_by_id(loop.active_snapshot_version_id)
        if not snapshot:
            raise BadRequestAppException("active snapshot version does not exist")
        return loop, snapshot

    @transactional
    async def init_loop_snapshot(
        self,
        *,
        loop_id: uuid.UUID,
        payload: dict[str, Any],
        actor_user_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode not in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION}:
            raise BadRequestAppException("snapshot init is only available for active_learning/simulation loop")
        if loop.active_snapshot_version_id:
            raise BadRequestAppException("active snapshot already exists; use snapshot:update")

        sample_ids_payload = payload.get("sample_ids") or []
        sample_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in sample_ids_payload])
        if loop.mode == LoopMode.SIMULATION:
            oracle_commit_id = await self._resolve_simulation_oracle_commit_id(loop=loop)
            oracle_labeled_sample_ids = await self._list_labeled_sample_ids_at_commit(commit_id=oracle_commit_id)
            oracle_labeled_set = set(oracle_labeled_sample_ids)
            if sample_ids:
                out_of_oracle_scope_ids = [sample_id for sample_id in sample_ids if sample_id not in oracle_labeled_set]
                if out_of_oracle_scope_ids:
                    preview = ",".join(str(sample_id) for sample_id in out_of_oracle_scope_ids[:5])
                    raise BadRequestAppException(
                        f"snapshot sample_ids must be subset of oracle labeled samples: {preview}"
                    )
            else:
                sample_ids = oracle_labeled_sample_ids
        elif not sample_ids:
            sample_ids = await self._list_project_sample_ids(loop.project_id)
        if not sample_ids:
            raise BadRequestAppException("no samples found for snapshot init")

        version_index = await self.al_snapshot_version_repo.next_version_index(loop.id)
        seed = self._resolve_snapshot_seed(loop=loop)
        train_seed_ratio = float(payload.get("train_seed_ratio", 0.05))
        val_ratio = float(payload.get("val_ratio", 0.1))
        test_ratio = float(payload.get("test_ratio", 0.1))
        val_policy = self._parse_enum(
            SnapshotValPolicy,
            payload.get("val_policy"),
            field_name="val_policy",
            default=SnapshotValPolicy.ANCHOR_ONLY,
        )

        sample_records = await self._list_snapshot_sample_records(sample_ids=sample_ids)
        assignment_rows = self._assign_init_partitions(
            sample_ids=sample_ids,
            sample_records=sample_records,
            seed=seed,
            test_ratio=test_ratio,
            val_ratio=val_ratio,
            train_seed_ratio=train_seed_ratio,
        )
        manifest_hash = self._manifest_hash(assignment_rows)
        snapshot = await self.al_snapshot_version_repo.create(
            {
                "loop_id": loop.id,
                "version_index": version_index,
                "parent_version_id": None,
                "update_mode": SnapshotUpdateMode.INIT,
                "val_policy": val_policy,
                "seed": seed,
                "rule_json": {
                    "train_seed_ratio": train_seed_ratio,
                    "val_ratio": val_ratio,
                    "test_ratio": test_ratio,
                    "val_policy": val_policy.value,
                },
                "manifest_hash": manifest_hash,
                "sample_count": len(assignment_rows),
                "created_by": actor_user_id,
            }
        )
        await self.al_snapshot_sample_repo.replace_snapshot_rows(
            snapshot_version_id=snapshot.id,
            rows=assignment_rows,
        )

        reveal_commit_id = await self._resolve_reveal_source_commit_id(loop=loop)
        visibility_rows: list[dict] = []
        for row in assignment_rows:
            partition = row["partition"]
            visible = partition == SnapshotPartition.TRAIN_SEED
            source = VisibilitySource.SEED_INIT if visible else VisibilitySource.SNAPSHOT_INIT
            visibility_rows.append(
                self.al_loop_visibility_repo.build_row(
                    loop_id=loop.id,
                    sample_id=row["sample_id"],
                    visible_in_train=visible,
                    source=source,
                    revealed_round_index=0 if visible else None,
                    reveal_commit_id=reveal_commit_id if visible else None,
                )
            )
        await self.al_loop_visibility_repo.upsert_rows(visibility_rows)

        await self.loop_repo.update_or_raise(
            loop.id,
            {
                "active_snapshot_version_id": snapshot.id,
            },
        )
        gate, _gate_meta, _primary_action, _actions = await self._compute_loop_gate(loop.id)
        return {
            "loop_id": loop.id,
            "gate": gate,
            "active_snapshot_version_id": snapshot.id,
            "version_index": version_index,
            "created": True,
            "sample_count": len(assignment_rows),
        }

    @transactional
    async def update_loop_snapshot(
        self,
        *,
        loop_id: uuid.UUID,
        payload: dict[str, Any],
        actor_user_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        loop, parent = await self._get_active_snapshot_or_raise(loop_id)
        mode = self._parse_enum(
            SnapshotUpdateMode,
            payload.get("mode"),
            field_name="mode",
            default=SnapshotUpdateMode.APPEND_ALL_TO_POOL,
        )
        if mode == SnapshotUpdateMode.INIT:
            raise BadRequestAppException("snapshot:update does not allow mode=init")

        existing_rows = await self.al_snapshot_sample_repo.list_by_snapshot(parent.id)
        existing_sample_ids = {row.sample_id for row in existing_rows}

        sample_ids_payload = payload.get("sample_ids") or []
        if sample_ids_payload:
            candidate_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in sample_ids_payload])
            if loop.mode == LoopMode.SIMULATION:
                oracle_commit_id = await self._resolve_simulation_oracle_commit_id(loop=loop)
                oracle_labeled_sample_ids = await self._list_labeled_sample_ids_at_commit(commit_id=oracle_commit_id)
                oracle_labeled_set = set(oracle_labeled_sample_ids)
                out_of_oracle_scope_ids = [sample_id for sample_id in candidate_ids if sample_id not in oracle_labeled_set]
                if out_of_oracle_scope_ids:
                    preview = ",".join(str(sample_id) for sample_id in out_of_oracle_scope_ids[:5])
                    raise BadRequestAppException(
                        f"snapshot sample_ids must be subset of oracle labeled samples: {preview}"
                    )
        else:
            if loop.mode == LoopMode.SIMULATION:
                oracle_commit_id = await self._resolve_simulation_oracle_commit_id(loop=loop)
                oracle_labeled_sample_ids = await self._list_labeled_sample_ids_at_commit(commit_id=oracle_commit_id)
                candidate_ids = [
                    sample_id for sample_id in oracle_labeled_sample_ids if sample_id not in existing_sample_ids
                ]
            else:
                all_sample_ids = await self._list_project_sample_ids(loop.project_id)
                candidate_ids = [sample_id for sample_id in all_sample_ids if sample_id not in existing_sample_ids]
        new_sample_ids = [sample_id for sample_id in candidate_ids if sample_id not in existing_sample_ids]
        if not new_sample_ids:
            gate, _gate_meta, _primary_action, _actions = await self._compute_loop_gate(loop.id)
            return {
                "loop_id": loop.id,
                "gate": gate,
                "active_snapshot_version_id": parent.id,
                "version_index": int(parent.version_index),
                "created": False,
                "sample_count": int(parent.sample_count),
            }

        version_index = await self.al_snapshot_version_repo.next_version_index(loop.id)
        seed = self._resolve_snapshot_seed(loop=loop)
        val_policy = parent.val_policy
        if payload.get("val_policy"):
            val_policy = self._parse_enum(
                SnapshotValPolicy,
                payload.get("val_policy"),
                field_name="val_policy",
            )

        merged_rows: list[dict[str, Any]] = [
            {
                "sample_id": row.sample_id,
                "partition": row.partition,
                "cohort_index": int(row.cohort_index),
                "locked": bool(row.locked),
            }
            for row in existing_rows
        ]
        if mode == SnapshotUpdateMode.APPEND_ALL_TO_POOL:
            for sample_id in new_sample_ids:
                merged_rows.append(
                    {
                        "sample_id": sample_id,
                        "partition": SnapshotPartition.TRAIN_POOL,
                        "cohort_index": version_index,
                        "locked": False,
                    }
                )
            rule_json = {
                "mode": mode.value,
                "seed": seed,
                "val_policy": val_policy.value,
            }
        else:
            batch_test_ratio = float(payload.get("batch_test_ratio", 0.1))
            batch_val_ratio = float(payload.get("batch_val_ratio", 0.1))
            new_sample_records = await self._list_snapshot_sample_records(sample_ids=new_sample_ids)
            append_rows = self._assign_append_split_partitions(
                sample_ids=new_sample_ids,
                sample_records=new_sample_records,
                seed=seed,
                cohort_index=version_index,
                test_ratio=batch_test_ratio,
                val_ratio=batch_val_ratio,
                val_policy=val_policy,
            )
            merged_rows.extend(append_rows)
            rule_json = {
                "mode": mode.value,
                "seed": seed,
                "batch_test_ratio": batch_test_ratio,
                "batch_val_ratio": batch_val_ratio,
                "val_policy": val_policy.value,
            }

        manifest_hash = self._manifest_hash(merged_rows)
        snapshot = await self.al_snapshot_version_repo.create(
            {
                "loop_id": loop.id,
                "version_index": version_index,
                "parent_version_id": parent.id,
                "update_mode": mode,
                "val_policy": val_policy,
                "seed": seed,
                "rule_json": rule_json,
                "manifest_hash": manifest_hash,
                "sample_count": len(merged_rows),
                "created_by": actor_user_id,
            }
        )
        await self.al_snapshot_sample_repo.replace_snapshot_rows(
            snapshot_version_id=snapshot.id,
            rows=merged_rows,
        )

        visibility_rows = [
            self.al_loop_visibility_repo.build_row(
                loop_id=loop.id,
                sample_id=sample_id,
                visible_in_train=False,
                source=VisibilitySource.SNAPSHOT_INIT,
                revealed_round_index=None,
                reveal_commit_id=None,
            )
            for sample_id in new_sample_ids
        ]
        await self.al_loop_visibility_repo.upsert_rows(visibility_rows)

        await self.loop_repo.update_or_raise(
            loop.id,
            {
                "active_snapshot_version_id": snapshot.id,
            },
        )
        gate, _gate_meta, _primary_action, _actions = await self._compute_loop_gate(loop.id)
        return {
            "loop_id": loop.id,
            "gate": gate,
            "active_snapshot_version_id": snapshot.id,
            "version_index": version_index,
            "created": True,
            "sample_count": len(merged_rows),
        }

    async def ensure_simulation_snapshot_bootstrap(
        self,
        *,
        loop_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> dict[str, Any] | None:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != LoopMode.SIMULATION:
            return None
        if loop.active_snapshot_version_id:
            return None

        simulation = self._extract_simulation_config(loop.config or {})
        snapshot_init_cfg = simulation.snapshot_init
        val_policy = self._parse_enum(
            SnapshotValPolicy,
            snapshot_init_cfg.val_policy,
            field_name="config.mode.snapshot_init.val_policy",
            default=SnapshotValPolicy.ANCHOR_ONLY,
        )
        payload = {
            "train_seed_ratio": float(snapshot_init_cfg.train_seed_ratio),
            "val_ratio": float(snapshot_init_cfg.val_ratio),
            "test_ratio": float(snapshot_init_cfg.test_ratio),
            "val_policy": val_policy.value,
        }
        try:
            return await self.init_loop_snapshot(
                loop_id=loop_id,
                payload=payload,
                actor_user_id=actor_user_id,
            )
        except BadRequestAppException as exc:
            if "active snapshot already exists" in str(exc):
                return None
            raise

    async def get_loop_snapshot(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode not in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION}:
            raise BadRequestAppException("snapshot is only available for active_learning/simulation loop")
        history = await self.al_snapshot_version_repo.list_by_loop(loop_id)
        active = None
        if loop.active_snapshot_version_id:
            active = await self.al_snapshot_version_repo.get_by_id(loop.active_snapshot_version_id)
        primary_view: dict[str, dict[str, Any]] = {
            "train": {"count": 0, "semantics": "effective_train"},
            "pool": {"count": 0, "semantics": "hidden_label_pool"},
            "val": {"count": 0, "semantics": "effective_val"},
            "test": {"count": 0, "semantics": "anchor_test"},
        }
        advanced_view: dict[str, Any] = {
            "bootstrap_seed": 0,
            "revealed_from_pool": 0,
            "pool_hidden": 0,
            "val_anchor": 0,
            "val_batch": 0,
            "test_anchor": 0,
            "test_batch": 0,
            "test_composite": 0,
            "manifest": {},
        }
        if active:
            rows = await self.al_snapshot_sample_repo.list_by_snapshot(active.id)
            counter = Counter([str(row.partition.value if hasattr(row.partition, "value") else row.partition) for row in rows])
            manifest = {key: int(value) for key, value in counter.items()}

            partition_by_sample_id: dict[uuid.UUID, SnapshotPartition] = {row.sample_id: row.partition for row in rows}
            visible_sample_ids = set(await self.al_loop_visibility_repo.list_visible_sample_ids(loop_id))
            train_visible_total = int(len(visible_sample_ids))
            train_visible_revealed_from_pool = int(
                sum(
                    1
                    for sample_id in visible_sample_ids
                    if partition_by_sample_id.get(sample_id) == SnapshotPartition.TRAIN_POOL
                )
            )
            train_pool_total = int(
                sum(1 for partition in partition_by_sample_id.values() if partition == SnapshotPartition.TRAIN_POOL)
            )
            train_pool_hidden = max(0, train_pool_total - train_visible_revealed_from_pool)
            val_anchor = int(counter.get(SnapshotPartition.VAL_ANCHOR.value, 0))
            val_batch = int(counter.get(SnapshotPartition.VAL_BATCH.value, 0))
            test_anchor = int(counter.get(SnapshotPartition.TEST_ANCHOR.value, 0))
            test_batch = int(counter.get(SnapshotPartition.TEST_BATCH.value, 0))
            val_effective = val_anchor
            if active.val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
                val_effective += val_batch
            primary_view = {
                "train": {"count": train_visible_total, "semantics": "effective_train"},
                "pool": {"count": int(train_pool_hidden), "semantics": "hidden_label_pool"},
                "val": {"count": int(val_effective), "semantics": "effective_val"},
                "test": {"count": int(test_anchor), "semantics": "anchor_test"},
            }
            advanced_view = {
                "bootstrap_seed": int(counter.get(SnapshotPartition.TRAIN_SEED.value, 0)),
                "revealed_from_pool": int(train_visible_revealed_from_pool),
                "pool_hidden": int(train_pool_hidden),
                "val_anchor": int(val_anchor),
                "val_batch": int(val_batch),
                "test_anchor": int(test_anchor),
                "test_batch": int(test_batch),
                "test_composite": int(test_anchor + test_batch),
                "manifest": manifest,
            }
        return {
            "loop_id": loop.id,
            "active_snapshot_version_id": loop.active_snapshot_version_id,
            "active": active,
            "history": history,
            "primary_view": primary_view,
            "advanced_view": advanced_view,
        }
