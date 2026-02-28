"""Snapshot and stage mixin for active-learning runtime."""

from __future__ import annotations

import hashlib
import random
import uuid
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import distinct
from sqlmodel import select

from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.exceptions import ConflictAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.project import ProjectDataset
from saki_api.modules.runtime.domain.al_snapshot_sample import ALSnapshotSample
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.shared.modeling.enums import (
    LoopMode,
    LoopStage,
    LoopStatus,
    RoundStatus,
    SnapshotPartition,
    SnapshotUpdateMode,
    SnapshotValPolicy,
    StepStatus,
    StepType,
    VisibilitySource,
    CommitSampleReviewState,
)
from saki_api.modules.storage.domain.sample import Sample


@dataclass(slots=True)
class _RevealProbe:
    selected_count: int
    revealable_count: int
    missing_count: int
    missing_sample_ids: list[uuid.UUID]
    revealable_sample_ids: list[uuid.UUID]
    latest_commit_id: uuid.UUID | None


class SnapshotMixin:
    @staticmethod
    def _effective_round_min_required(*, selected_count: int, configured_min_required: int) -> int:
        configured = max(1, int(configured_min_required or 1))
        selected = max(0, int(selected_count or 0))
        if selected <= 0:
            return 0
        return min(configured, selected)

    def _compute_seed(self, *, loop_id: uuid.UUID, version_index: int, requested_seed: str | None) -> str:
        raw = str(requested_seed or "").strip()
        if raw:
            return raw
        payload = f"{loop_id}:{version_index}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _manifest_hash(rows: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for row in sorted(rows, key=lambda item: str(item["sample_id"])):
            digest.update(
                f"{row['sample_id']}|{row['partition']}|{int(row.get('cohort_index', 0))}|{int(bool(row.get('locked', False)))}".encode(
                    "utf-8"
                )
            )
        return digest.hexdigest()

    @staticmethod
    def _hash_sample_ids(sample_ids: list[uuid.UUID]) -> str:
        digest = hashlib.sha256()
        for sample_id in sorted({str(item) for item in sample_ids}):
            digest.update(sample_id.encode("utf-8"))
        return digest.hexdigest()

    @staticmethod
    def _action(
        key: str,
        *,
        label: str,
        runnable: bool = True,
        requires_confirm: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "runnable": bool(runnable),
            "requires_confirm": bool(requires_confirm),
            "payload": payload or {},
        }

    @staticmethod
    def _action_keys(actions: list[dict[str, Any]]) -> set[str]:
        return {
            str(item.get("key") or "").strip()
            for item in actions
            if str(item.get("key") or "").strip()
        }

    @staticmethod
    def _enum_text(raw: Any) -> str:
        if hasattr(raw, "value"):
            return str(raw.value)
        return str(raw)

    @staticmethod
    def _decision_token_payload(
        *,
        loop: Any,
        stage: LoopStage,
        stage_meta: dict[str, Any],
        actions: list[dict[str, Any]],
        latest_round: Any | None,
        branch_head_commit_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        return {
            "loop_id": str(loop.id),
            "loop_updated_at": str(getattr(loop, "updated_at", "")),
            "loop_status": SnapshotMixin._enum_text(loop.status),
            "loop_phase": SnapshotMixin._enum_text(loop.phase),
            "loop_mode": SnapshotMixin._enum_text(loop.mode),
            "active_snapshot_version_id": str(loop.active_snapshot_version_id or ""),
            "stage": SnapshotMixin._enum_text(stage),
            "stage_meta": stage_meta,
            "actions": [
                {
                    "key": str(item.get("key") or ""),
                    "runnable": bool(item.get("runnable", True)),
                    "requires_confirm": bool(item.get("requires_confirm", False)),
                    "payload": item.get("payload") if isinstance(item.get("payload"), dict) else {},
                }
                for item in actions
            ],
            "latest_round": {
                "id": str(getattr(latest_round, "id", "") or ""),
                "round_index": int(getattr(latest_round, "round_index", 0) or 0),
                "attempt_index": int(getattr(latest_round, "attempt_index", 0) or 0),
                "state": SnapshotMixin._enum_text(getattr(latest_round, "state", "") or ""),
                "updated_at": str(getattr(latest_round, "updated_at", "") or ""),
            }
            if latest_round
            else None,
            "branch_head_commit_id": str(branch_head_commit_id or ""),
        }

    @staticmethod
    def _make_decision_token(payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(str(payload).encode("utf-8"))
        return digest.hexdigest()

    def _merge_stage_actions(
        self,
        *,
        loop: Any,
        stage: LoopStage,
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = list(actions)
        keys = self._action_keys(merged)

        def _append(action: dict[str, Any]) -> None:
            key = str(action.get("key") or "").strip()
            if not key or key in keys:
                return
            merged.append(action)
            keys.add(key)

        lifecycle_stage_allowlist = {
            LoopStage.READY_TO_START,
            LoopStage.RUNNING_ROUND,
            LoopStage.WAITING_ROUND_LABEL,
            LoopStage.READY_TO_CONFIRM,
            LoopStage.FAILED_RETRYABLE,
        }
        if stage in lifecycle_stage_allowlist:
            status_text = str(loop.status.value if hasattr(loop.status, "value") else loop.status).strip().lower()
            if status_text == LoopStatus.DRAFT.value and stage == LoopStage.READY_TO_START:
                _append(self._action("start", label="Start"))
            elif status_text == LoopStatus.RUNNING.value:
                _append(self._action("pause", label="Pause"))
                _append(self._action("stop", label="Stop"))
            elif status_text == LoopStatus.PAUSED.value:
                _append(self._action("resume", label="Resume"))
                _append(self._action("stop", label="Stop"))
            elif status_text == LoopStatus.STOPPING.value:
                _append(self._action("observe", label="Observe", runnable=False))

        if (
            loop.mode == LoopMode.ACTIVE_LEARNING
            and loop.active_snapshot_version_id
            and stage
            in {
                LoopStage.READY_TO_START,
                LoopStage.RUNNING_ROUND,
                LoopStage.WAITING_ROUND_LABEL,
                LoopStage.READY_TO_CONFIRM,
            }
        ):
            _append(self._action("snapshot_update", label="Update Snapshot"))
        return merged

    def _build_blocking_reasons(
        self,
        *,
        stage: LoopStage,
        stage_meta: dict[str, Any],
        primary_action: dict[str, Any] | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not primary_action:
            reasons.append("no_primary_action")
        elif not bool(primary_action.get("runnable", True)):
            reasons.append(f"primary_action_not_runnable:{primary_action.get('key')}")

        if stage == LoopStage.SNAPSHOT_REQUIRED:
            reasons.append("snapshot_required")
        if stage == LoopStage.LABEL_GAP_REQUIRED:
            reasons.append(f"annotation_gap:{int(stage_meta.get('gap_count') or 0)}")
        if stage == LoopStage.WAITING_ROUND_LABEL:
            reasons.append(
                f"need_more_labels:{int(stage_meta.get('revealed_count') or 0)}/"
                f"{int(stage_meta.get('min_required') or 0)}"
            )
        if stage == LoopStage.FAILED:
            reasons.append("loop_failed")
        return reasons

    async def _get_branch_head_commit_id(self, branch_id: uuid.UUID) -> uuid.UUID | None:
        stmt = select(Branch.head_commit_id).where(Branch.id == branch_id)
        return (await self.session.exec(stmt)).one_or_none()

    @staticmethod
    def _parse_enum(
        enum_cls: type[Enum],
        raw: Any,
        *,
        field_name: str,
        default: Any | None = None,
    ) -> Any:
        if raw is None:
            if default is not None:
                return default
            raise BadRequestAppException(f"{field_name} is required")
        if isinstance(raw, enum_cls):
            return raw
        if isinstance(raw, Enum):
            raw = raw.value

        text = str(raw).strip()
        if not text:
            if default is not None:
                return default
            raise BadRequestAppException(f"{field_name} is required")

        direct_candidates = [text]
        if "." in text:
            direct_candidates.append(text.rsplit(".", maxsplit=1)[-1])

        for candidate in direct_candidates:
            try:
                return enum_cls(candidate)
            except ValueError:
                pass
            try:
                return enum_cls[candidate]
            except KeyError:
                pass
            try:
                return enum_cls[candidate.upper()]
            except KeyError:
                pass
            try:
                return enum_cls[candidate.lower()]
            except KeyError:
                pass

        allowed_values = ", ".join(sorted(str(item.value) for item in enum_cls))
        allowed_names = ", ".join(sorted(str(item.name) for item in enum_cls))
        raise BadRequestAppException(
            f"invalid {field_name}: {raw}. allowed values=[{allowed_values}], names=[{allowed_names}]"
        )

    async def _list_project_sample_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        dataset_ids = list(
            (
                await self.session.exec(
                    select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
                )
            ).all()
        )
        if not dataset_ids:
            return []
        stmt = (
            select(Sample.id)
            .where(Sample.dataset_id.in_(dataset_ids))
            .order_by(Sample.id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    @staticmethod
    def _allocate_counts(
        *,
        total: int,
        test_ratio: float,
        val_ratio: float,
        train_seed_ratio: float,
    ) -> tuple[int, int, int]:
        if total <= 0:
            return 0, 0, 0
        test_count = max(0, min(total, int(round(total * test_ratio))))
        val_count = max(0, min(total - test_count, int(round(total * val_ratio))))
        train_seed_count = max(0, min(total - test_count - val_count, int(round(total * train_seed_ratio))))
        while test_count + val_count + train_seed_count > total:
            if train_seed_count > 0:
                train_seed_count -= 1
            elif val_count > 0:
                val_count -= 1
            else:
                test_count -= 1
        return test_count, val_count, train_seed_count

    @staticmethod
    def _assign_init_partitions(
        *,
        sample_ids: list[uuid.UUID],
        seed: str,
        test_ratio: float,
        val_ratio: float,
        train_seed_ratio: float,
    ) -> list[dict[str, Any]]:
        ordered = sorted(sample_ids, key=lambda item: str(item))
        randomizer = random.Random(seed)
        randomizer.shuffle(ordered)
        total = len(ordered)
        test_count, val_count, train_seed_count = SnapshotMixin._allocate_counts(
            total=total,
            test_ratio=test_ratio,
            val_ratio=val_ratio,
            train_seed_ratio=train_seed_ratio,
        )
        test_ids = ordered[:test_count]
        val_ids = ordered[test_count:test_count + val_count]
        seed_ids = ordered[test_count + val_count:test_count + val_count + train_seed_count]
        pool_ids = ordered[test_count + val_count + train_seed_count:]

        rows: list[dict[str, Any]] = []
        for sample_id in test_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.TEST_ANCHOR,
                    "cohort_index": 0,
                    "locked": True,
                }
            )
        for sample_id in val_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.VAL_ANCHOR,
                    "cohort_index": 0,
                    "locked": True,
                }
            )
        for sample_id in seed_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.TRAIN_SEED,
                    "cohort_index": 0,
                    "locked": False,
                }
            )
        for sample_id in pool_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.TRAIN_POOL,
                    "cohort_index": 0,
                    "locked": False,
                }
            )
        return rows

    @staticmethod
    def _assign_append_split_partitions(
        *,
        sample_ids: list[uuid.UUID],
        seed: str,
        cohort_index: int,
        test_ratio: float,
        val_ratio: float,
        val_policy: SnapshotValPolicy,
    ) -> list[dict[str, Any]]:
        ordered = sorted(sample_ids, key=lambda item: str(item))
        randomizer = random.Random(seed)
        randomizer.shuffle(ordered)
        total = len(ordered)
        test_count = max(0, min(total, int(round(total * test_ratio))))
        val_count = 0
        if val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
            val_count = max(0, min(total - test_count, int(round(total * val_ratio))))
        while test_count + val_count > total:
            if val_count > 0:
                val_count -= 1
            else:
                test_count -= 1
        test_ids = ordered[:test_count]
        val_ids = ordered[test_count:test_count + val_count]
        pool_ids = ordered[test_count + val_count:]

        rows: list[dict[str, Any]] = []
        for sample_id in test_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.TEST_BATCH,
                    "cohort_index": cohort_index,
                    "locked": True,
                }
            )
        for sample_id in val_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.VAL_BATCH,
                    "cohort_index": cohort_index,
                    "locked": True,
                }
            )
        for sample_id in pool_ids:
            rows.append(
                {
                    "sample_id": sample_id,
                    "partition": SnapshotPartition.TRAIN_POOL,
                    "cohort_index": cohort_index,
                    "locked": False,
                }
            )
        return rows

    async def _get_active_snapshot_or_raise(self, loop_id: uuid.UUID) -> tuple[Any, ALSnapshotVersion]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("snapshot is only available for active_learning loop")
        if not loop.active_snapshot_version_id:
            raise BadRequestAppException("loop has no active snapshot")
        snapshot = await self.al_snapshot_version_repo.get_by_id(loop.active_snapshot_version_id)
        if not snapshot:
            raise BadRequestAppException("active snapshot version does not exist")
        return loop, snapshot

    async def _count_labeled_samples(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not sample_ids:
            return set()
        unique_sample_ids = list(set(sample_ids))

        # Primary source: commit sample review state. EMPTY_CONFIRMED counts as labeled.
        review_stmt = (
            select(distinct(CommitSampleState.sample_id))
            .where(
                CommitSampleState.commit_id == commit_id,
                CommitSampleState.sample_id.in_(unique_sample_ids),
                CommitSampleState.state.in_(
                    (
                        CommitSampleReviewState.LABELED,
                        CommitSampleReviewState.EMPTY_CONFIRMED,
                    )
                ),
            )
        )
        reviewed_ids = set((await self.session.exec(review_stmt)).all())
        if len(reviewed_ids) == len(unique_sample_ids):
            return reviewed_ids

        # Compatibility fallback for legacy commits where sample review state might be missing.
        remaining_ids = [sample_id for sample_id in unique_sample_ids if sample_id not in reviewed_ids]
        if not remaining_ids:
            return reviewed_ids
        stmt = (
            select(distinct(CommitAnnotationMap.sample_id))
            .where(
                CommitAnnotationMap.commit_id == commit_id,
                CommitAnnotationMap.sample_id.in_(remaining_ids),
            )
        )
        reviewed_ids.update((await self.session.exec(stmt)).all())
        return reviewed_ids

    async def _load_selected_sample_ids(
        self,
        *,
        loop_id: uuid.UUID,
        round_index: int,
    ) -> list[uuid.UUID]:
        stmt = (
            select(StepCandidateItem.sample_id)
            .join(Step, Step.id == StepCandidateItem.step_id)
            .join(Round, Round.id == Step.round_id)
            .where(
                Round.loop_id == loop_id,
                Round.round_index == round_index,
                Step.step_type == StepType.SELECT,
            )
            .order_by(StepCandidateItem.rank.asc(), StepCandidateItem.created_at.asc())
        )
        rows = list((await self.session.exec(stmt)).all())
        if not rows:
            return []
        ordered: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for sample_id in rows:
            if sample_id in seen:
                continue
            seen.add(sample_id)
            ordered.append(sample_id)
        return ordered

    async def _probe_round_reveal(
        self,
        *,
        loop_id: uuid.UUID,
        round_index: int,
    ) -> _RevealProbe:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        latest_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        selected_sample_ids = await self._load_selected_sample_ids(loop_id=loop_id, round_index=round_index)
        if not selected_sample_ids:
            return _RevealProbe(
                selected_count=0,
                revealable_count=0,
                missing_count=0,
                missing_sample_ids=[],
                revealable_sample_ids=[],
                latest_commit_id=latest_commit_id,
            )
        if not latest_commit_id:
            return _RevealProbe(
                selected_count=len(selected_sample_ids),
                revealable_count=0,
                missing_count=len(selected_sample_ids),
                missing_sample_ids=list(selected_sample_ids),
                revealable_sample_ids=[],
                latest_commit_id=None,
            )
        labeled_ids = await self._count_labeled_samples(commit_id=latest_commit_id, sample_ids=selected_sample_ids)
        visible_ids = set(await self.al_loop_visibility_repo.list_visible_sample_ids(loop_id))
        revealable = [sample_id for sample_id in selected_sample_ids if sample_id in labeled_ids and sample_id not in visible_ids]
        missing = [sample_id for sample_id in selected_sample_ids if sample_id not in labeled_ids]
        return _RevealProbe(
            selected_count=len(selected_sample_ids),
            revealable_count=len(revealable),
            missing_count=len(missing),
            missing_sample_ids=missing,
            revealable_sample_ids=revealable,
            latest_commit_id=latest_commit_id,
        )

    @transactional
    async def resolve_round_reveal(
        self,
        *,
        loop_id: uuid.UUID,
        round_index: int,
        branch_id: uuid.UUID | None = None,
        force: bool = False,
        min_required: int = 1,
    ) -> dict[str, Any]:
        loop, _snapshot = await self._get_active_snapshot_or_raise(loop_id)
        if round_index <= 0:
            raise BadRequestAppException("round_index must be positive")
        if branch_id and branch_id != loop.branch_id:
            raise BadRequestAppException("branch_id does not match loop")

        probe = await self._probe_round_reveal(loop_id=loop_id, round_index=round_index)
        threshold = self._effective_round_min_required(
            selected_count=probe.selected_count,
            configured_min_required=int(min_required or 1),
        )
        if not force and probe.revealable_count < threshold:
            raise BadRequestAppException(
                f"not enough revealable samples: {probe.revealable_count} < {threshold}"
            )

        revealed_ids = probe.revealable_sample_ids
        if revealed_ids:
            source = VisibilitySource.FORCE_REVEAL if force else VisibilitySource.ROUND_REVEAL
            rows = [
                self.al_loop_visibility_repo.build_row(
                    loop_id=loop_id,
                    sample_id=sample_id,
                    visible_in_train=True,
                    source=source,
                    revealed_round_index=round_index,
                    reveal_commit_id=probe.latest_commit_id,
                )
                for sample_id in revealed_ids
            ]
            await self.al_loop_visibility_repo.upsert_rows(rows)

        return {
            "loop_id": loop_id,
            "round_index": round_index,
            "revealed_count": len(revealed_ids),
            "selected_count": int(probe.selected_count),
            "missing_count": int(probe.missing_count),
            "effective_min_required": int(threshold),
            "latest_commit_id": probe.latest_commit_id,
            "revealable_sample_ids_hash": self._hash_sample_ids(revealed_ids),
        }

    async def _compute_annotation_gaps_internal(self, loop_id: uuid.UUID) -> dict[str, Any]:
        loop, snapshot = await self._get_active_snapshot_or_raise(loop_id)
        commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        rows = await self.al_snapshot_sample_repo.list_by_snapshot(snapshot.id)
        partition_map: dict[SnapshotPartition, list[uuid.UUID]] = {}
        for row in rows:
            partition_map.setdefault(row.partition, []).append(row.sample_id)

        seed_ids = partition_map.get(SnapshotPartition.TRAIN_SEED, [])
        val_ids = list(partition_map.get(SnapshotPartition.VAL_ANCHOR, []))
        if snapshot.val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
            val_ids.extend(partition_map.get(SnapshotPartition.VAL_BATCH, []))
        test_ids = list(partition_map.get(SnapshotPartition.TEST_ANCHOR, []))
        test_ids.extend(partition_map.get(SnapshotPartition.TEST_BATCH, []))

        labeled_ids: set[uuid.UUID] = set()
        if commit_id:
            check_ids = list({*seed_ids, *val_ids, *test_ids})
            labeled_ids = await self._count_labeled_samples(commit_id=commit_id, sample_ids=check_ids)

        def _bucket(partition: SnapshotPartition, sample_ids: list[uuid.UUID]) -> dict[str, Any]:
            missing = [sample_id for sample_id in sample_ids if sample_id not in labeled_ids]
            return {
                "partition": partition,
                "total": len(sample_ids),
                "missing_count": len(missing),
                "sample_ids": missing,
            }

        query_bucket = {"partition": SnapshotPartition.TRAIN_POOL, "total": 0, "missing_count": 0, "sample_ids": []}
        latest_round = await self.repository.get_latest_by_loop(loop_id)
        if latest_round and int(latest_round.round_index) > 0:
            probe = await self._probe_round_reveal(loop_id=loop_id, round_index=int(latest_round.round_index))
            query_bucket = {
                "partition": SnapshotPartition.TRAIN_POOL,
                "total": int(probe.selected_count),
                "missing_count": int(probe.missing_count),
                "sample_ids": list(probe.missing_sample_ids),
            }

        return {
            "loop_id": loop_id,
            "commit_id": commit_id,
            "buckets": [
                _bucket(SnapshotPartition.TRAIN_SEED, seed_ids),
                _bucket(SnapshotPartition.VAL_ANCHOR, val_ids),
                _bucket(SnapshotPartition.TEST_ANCHOR, test_ids),
                query_bucket,
            ],
        }

    async def _compute_loop_stage(
        self,
        loop_id: uuid.UUID,
    ) -> tuple[LoopStage, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        read_action = self._action("read", label="Read", runnable=False)
        observe_action = self._action("observe", label="Observe", runnable=False)
        start_action = self._action("start", label="Start")

        if loop.status == LoopStatus.FAILED:
            latest_round = await self.repository.get_latest_by_loop(loop_id)
            # BUGFIX(2026-02-27): normalize enum/text status to avoid missing retryable stage
            # when DB stores uppercase enum while API enums are lowercase values.
            latest_round_state = (
                str(latest_round.state.value if hasattr(latest_round.state, "value") else latest_round.state).strip().lower()
                if latest_round
                else ""
            )
            if latest_round and latest_round_state == RoundStatus.FAILED.value:
                steps = await self.step_repo.list_by_round(latest_round.id)
                # BUGFIX(2026-02-27): only DISPATCHING/RUNNING/RETRYING should block retry;
                # PENDING trailing steps in a failed round are expected and should not block.
                has_inflight_steps = any(
                    str(step.state.value if hasattr(step.state, "value") else step.state).strip().lower()
                    in {
                        StepStatus.RUNNING.value,
                        StepStatus.DISPATCHING.value,
                        StepStatus.RETRYING.value,
                    }
                    for step in steps
                )
                if not has_inflight_steps:
                    retry_action = self._action(
                        "retry_round",
                        label="Retry Round",
                        payload={
                            "round_id": str(latest_round.id),
                            "round_index": int(latest_round.round_index),
                            "attempt_index": int(latest_round.attempt_index),
                        },
                    )
                    stage_meta = {
                        "reason": "latest_round_failed",
                        "retry_round_id": str(latest_round.id),
                        "retry_round_index": int(latest_round.round_index),
                        "retry_attempt_index": int(latest_round.attempt_index),
                        "retry_reason_hint": str(latest_round.terminal_reason or ""),
                    }
                    return LoopStage.FAILED_RETRYABLE, stage_meta, retry_action, [retry_action, read_action]
            return LoopStage.FAILED, {"reason": "terminal"}, None, [read_action]

        if loop.status == LoopStatus.COMPLETED:
            return LoopStage.COMPLETED, {"reason": "terminal"}, None, [read_action]
        if loop.status == LoopStatus.STOPPED:
            return LoopStage.STOPPED, {"reason": "terminal"}, None, [read_action]

        if loop.mode != LoopMode.ACTIVE_LEARNING:
            if loop.status in {LoopStatus.RUNNING, LoopStatus.PAUSED, LoopStatus.STOPPING}:
                return LoopStage.RUNNING_ROUND, {"mode": str(loop.mode)}, None, [observe_action]
            return LoopStage.READY_TO_START, {"mode": str(loop.mode)}, start_action, [start_action]

        if not loop.active_snapshot_version_id:
            snapshot_action = self._action("snapshot_init", label="Init Snapshot")
            return LoopStage.SNAPSHOT_REQUIRED, {"missing": "snapshot"}, snapshot_action, [snapshot_action, read_action]

        gaps = await self._compute_annotation_gaps_internal(loop_id)
        gap_total = 0
        for bucket in gaps["buckets"]:
            partition = bucket["partition"]
            if partition in {
                SnapshotPartition.TRAIN_SEED,
                SnapshotPartition.VAL_ANCHOR,
                SnapshotPartition.TEST_ANCHOR,
            }:
                gap_total += int(bucket["missing_count"])
        if gap_total > 0:
            gap_action = self._action("view_annotation_gaps", label="Resolve Annotation Gaps", runnable=False)
            return LoopStage.LABEL_GAP_REQUIRED, {"gap_count": gap_total}, gap_action, [gap_action, read_action]

        if loop.status in {LoopStatus.RUNNING, LoopStatus.PAUSED, LoopStatus.STOPPING}:
            if str(loop.phase.value if hasattr(loop.phase, "value") else loop.phase) == "al_wait_user":
                latest_round = await self.repository.get_latest_by_loop(loop_id)
                round_index = int(latest_round.round_index) if latest_round else 0
                if round_index <= 0:
                    annotate_action = self._action("annotate", label="Annotate Query Samples", runnable=False)
                    return (
                        LoopStage.WAITING_ROUND_LABEL,
                        {"round_index": 0, "revealed_count": 0},
                        annotate_action,
                        [annotate_action],
                    )
                probe = await self._probe_round_reveal(loop_id=loop_id, round_index=round_index)
                configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
                effective_min_required = self._effective_round_min_required(
                    selected_count=probe.selected_count,
                    configured_min_required=configured_min_required,
                )
                if probe.revealable_count >= effective_min_required:
                    confirm_action = self._action("confirm", label="Confirm Round")
                    return (
                        LoopStage.READY_TO_CONFIRM,
                        {
                            "round_index": round_index,
                            "revealed_count": probe.revealable_count,
                            "selected_count": probe.selected_count,
                            "missing_count": probe.missing_count,
                            "min_required": effective_min_required,
                            "configured_min_required": configured_min_required,
                        },
                        confirm_action,
                        [confirm_action],
                    )
                annotate_action = self._action("annotate", label="Annotate Query Samples", runnable=False)
                return (
                    LoopStage.WAITING_ROUND_LABEL,
                    {
                        "round_index": round_index,
                        "revealed_count": probe.revealable_count,
                        "selected_count": probe.selected_count,
                        "missing_count": probe.missing_count,
                        "min_required": effective_min_required,
                        "configured_min_required": configured_min_required,
                    },
                    annotate_action,
                    [annotate_action],
                )
            return LoopStage.RUNNING_ROUND, {"phase": str(loop.phase)}, None, [observe_action]

        return LoopStage.READY_TO_START, {"phase": str(loop.phase)}, start_action, [start_action]

    @transactional
    async def init_loop_snapshot(
        self,
        *,
        loop_id: uuid.UUID,
        payload: dict[str, Any],
        actor_user_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("snapshot init is only available for active_learning loop")
        if loop.active_snapshot_version_id:
            raise BadRequestAppException("active snapshot already exists; use snapshot:update")

        sample_ids_payload = payload.get("sample_ids") or []
        if sample_ids_payload:
            sample_ids = list({uuid.UUID(str(item)) for item in sample_ids_payload})
        else:
            sample_ids = await self._list_project_sample_ids(loop.project_id)
        if not sample_ids:
            raise BadRequestAppException("no samples found for snapshot init")

        version_index = await self.al_snapshot_version_repo.next_version_index(loop.id)
        seed = self._compute_seed(loop_id=loop.id, version_index=version_index, requested_seed=payload.get("seed"))
        train_seed_ratio = float(payload.get("train_seed_ratio", 0.05))
        val_ratio = float(payload.get("val_ratio", 0.1))
        test_ratio = float(payload.get("test_ratio", 0.1))
        val_policy = self._parse_enum(
            SnapshotValPolicy,
            payload.get("val_policy"),
            field_name="val_policy",
            default=SnapshotValPolicy.ANCHOR_ONLY,
        )

        assignment_rows = self._assign_init_partitions(
            sample_ids=sample_ids,
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

        reveal_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
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
        stage, _stage_meta, _primary_action, _actions = await self._compute_loop_stage(loop.id)
        return {
            "loop_id": loop.id,
            "stage": stage,
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
            candidate_ids = list({uuid.UUID(str(item)) for item in sample_ids_payload})
        else:
            all_sample_ids = await self._list_project_sample_ids(loop.project_id)
            candidate_ids = [sample_id for sample_id in all_sample_ids if sample_id not in existing_sample_ids]
        new_sample_ids = [sample_id for sample_id in candidate_ids if sample_id not in existing_sample_ids]
        if not new_sample_ids:
            stage, _stage_meta, _primary_action, _actions = await self._compute_loop_stage(loop.id)
            return {
                "loop_id": loop.id,
                "stage": stage,
                "active_snapshot_version_id": parent.id,
                "version_index": int(parent.version_index),
                "created": False,
                "sample_count": int(parent.sample_count),
            }

        version_index = await self.al_snapshot_version_repo.next_version_index(loop.id)
        seed = self._compute_seed(loop_id=loop.id, version_index=version_index, requested_seed=payload.get("seed"))
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
            append_rows = self._assign_append_split_partitions(
                sample_ids=new_sample_ids,
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
        stage, _stage_meta, _primary_action, _actions = await self._compute_loop_stage(loop.id)
        return {
            "loop_id": loop.id,
            "stage": stage,
            "active_snapshot_version_id": snapshot.id,
            "version_index": version_index,
            "created": True,
            "sample_count": len(merged_rows),
        }

    async def get_loop_snapshot(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("snapshot is only available for active_learning loop")
        history = await self.al_snapshot_version_repo.list_by_loop(loop_id)
        active = None
        if loop.active_snapshot_version_id:
            active = await self.al_snapshot_version_repo.get_by_id(loop.active_snapshot_version_id)
        partition_counts: dict[str, int] = {}
        if active:
            rows = await self.al_snapshot_sample_repo.list_by_snapshot(active.id)
            counter = Counter([str(row.partition.value if hasattr(row.partition, "value") else row.partition) for row in rows])
            partition_counts = {key: int(value) for key, value in counter.items()}
        return {
            "loop_id": loop.id,
            "active_snapshot_version_id": loop.active_snapshot_version_id,
            "active": active,
            "history": history,
            "partition_counts": partition_counts,
        }

    async def get_loop_stage(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        stage, stage_meta, primary_action, stage_actions = await self._compute_loop_stage(loop_id)
        actions = self._merge_stage_actions(loop=loop, stage=stage, actions=stage_actions)
        latest_round = await self.repository.get_latest_by_loop(loop_id)
        branch_head_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        token_payload = self._decision_token_payload(
            loop=loop,
            stage=stage,
            stage_meta=stage_meta,
            actions=actions,
            latest_round=latest_round,
            branch_head_commit_id=branch_head_commit_id,
        )
        decision_token = self._make_decision_token(token_payload)
        blocking_reasons = self._build_blocking_reasons(
            stage=stage,
            stage_meta=stage_meta,
            primary_action=primary_action,
        )
        return {
            "loop_id": loop_id,
            "stage": stage,
            "stage_meta": stage_meta,
            "primary_action": primary_action,
            "actions": actions,
            "decision_token": decision_token,
            "blocking_reasons": blocking_reasons,
        }

    async def resolve_loop_action_request(
        self,
        *,
        loop_id: uuid.UUID,
        requested_action: str | None,
        decision_token: str | None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        decision = await self.get_loop_stage(loop_id=loop_id)
        latest_token = str(decision.get("decision_token") or "")
        if decision_token and latest_token and str(decision_token) != latest_token:
            raise ConflictAppException(
                message="decision token is stale",
                data={"expected": latest_token, "provided": str(decision_token)},
            )

        action_key = str(requested_action or "").strip().lower()
        if not action_key:
            primary_action = decision.get("primary_action")
            action_key = str((primary_action or {}).get("key") or "").strip().lower()
        if not action_key:
            raise BadRequestAppException("no actionable transition for current stage")

        actions = decision.get("actions") or []
        matched = None
        for item in actions:
            key = str((item or {}).get("key") or "").strip().lower()
            if key == action_key:
                matched = item
                break
        if matched is None:
            raise BadRequestAppException(f"action not allowed in current stage: {action_key}")
        if not bool(matched.get("runnable", True)):
            raise BadRequestAppException(f"action is not runnable in current stage: {action_key}")
        return decision, action_key, matched

    async def get_loop_annotation_gaps(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        return await self._compute_annotation_gaps_internal(loop_id)
