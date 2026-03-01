"""Snapshot and gate mixin for active-learning runtime."""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import asc, desc, distinct, func, or_
from sqlmodel import select

from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.exceptions import ConflictAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.annotation.repo.draft import AnnotationDraftRepository
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.project import ProjectDataset
from saki_api.modules.runtime.domain.prediction_set import PredictionSet
from saki_api.modules.runtime.domain.prediction_item import PredictionItem
from saki_api.modules.runtime.domain.al_snapshot_sample import ALSnapshotSample
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.shared.modeling.enums import (
    LoopPhase,
    LoopMode,
    RoundSelectionOverrideOp,
    LoopGate,
    LoopLifecycle,
    RoundStatus,
    SnapshotPartition,
    SnapshotUpdateMode,
    SnapshotValPolicy,
    StepStatus,
    StepType,
    VisibilitySource,
    CommitSampleReviewState,
)
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@dataclass(slots=True)
class _RevealProbe:
    selected_count: int
    revealable_count: int
    missing_count: int
    missing_sample_ids: list[uuid.UUID]
    revealable_sample_ids: list[uuid.UUID]
    latest_commit_id: uuid.UUID | None


@dataclass(slots=True)
class _RoundSelectionContext:
    loop: Any
    round_row: Round
    topk: int
    review_pool_size: int
    score_step: Step
    select_step: Step
    score_pool: list[StepCandidateItem]
    auto_selected: list[StepCandidateItem]


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
        gate: LoopGate,
        gate_meta: dict[str, Any],
        actions: list[dict[str, Any]],
        latest_round: Any | None,
        branch_head_commit_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        return {
            "loop_id": str(loop.id),
            "loop_updated_at": str(getattr(loop, "updated_at", "")),
            "loop_lifecycle": SnapshotMixin._enum_text(loop.lifecycle),
            "loop_phase": SnapshotMixin._enum_text(loop.phase),
            "loop_mode": SnapshotMixin._enum_text(loop.mode),
            "active_snapshot_version_id": str(loop.active_snapshot_version_id or ""),
            "gate": SnapshotMixin._enum_text(gate),
            "gate_meta": gate_meta,
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
                "confirmed_at": str(getattr(latest_round, "confirmed_at", "") or ""),
                "updated_at": str(getattr(latest_round, "updated_at", "") or ""),
            }
            if latest_round
            else None,
            "branch_head_commit_id": str(branch_head_commit_id or ""),
        }

    @staticmethod
    def _make_decision_token(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8"))
        return digest.hexdigest()

    def _merge_gate_actions(
        self,
        *,
        loop: Any,
        gate: LoopGate,
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
            LoopGate.CAN_START,
            LoopGate.RUNNING,
            LoopGate.PAUSED,
            LoopGate.STOPPING,
            LoopGate.NEED_ROUND_LABELS,
            LoopGate.CAN_CONFIRM,
            LoopGate.CAN_NEXT_ROUND,
            LoopGate.CAN_RETRY,
        }
        if gate in lifecycle_stage_allowlist:
            lifecycle_text = str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
            if lifecycle_text == LoopLifecycle.DRAFT.value and gate == LoopGate.CAN_START:
                _append(self._action("start", label="Start"))
            elif lifecycle_text == LoopLifecycle.RUNNING.value:
                _append(self._action("pause", label="Pause"))
                _append(self._action("stop", label="Stop"))
            elif lifecycle_text == LoopLifecycle.PAUSED.value:
                _append(self._action("resume", label="Resume"))
                _append(self._action("stop", label="Stop"))
            elif lifecycle_text == LoopLifecycle.STOPPING.value:
                _append(self._action("observe", label="Observe", runnable=False))

        if (
            loop.mode == LoopMode.ACTIVE_LEARNING
            and loop.active_snapshot_version_id
            and gate
            in {
                LoopGate.CAN_START,
                LoopGate.RUNNING,
                LoopGate.PAUSED,
                LoopGate.STOPPING,
                LoopGate.NEED_ROUND_LABELS,
                LoopGate.CAN_CONFIRM,
            }
        ):
            _append(self._action("snapshot_update", label="Update Snapshot"))
        return merged

    def _build_blocking_reasons(
        self,
        *,
        gate: LoopGate,
        gate_meta: dict[str, Any],
        primary_action: dict[str, Any] | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not primary_action:
            reasons.append("no_primary_action")
        elif not bool(primary_action.get("runnable", True)):
            reasons.append(f"primary_action_not_runnable:{primary_action.get('key')}")

        if gate == LoopGate.NEED_SNAPSHOT:
            reasons.append("need_snapshot")
        if gate == LoopGate.NEED_LABELS:
            reasons.append(f"need_labels:{int(gate_meta.get('gap_count') or 0)}")
        if gate == LoopGate.NEED_ROUND_LABELS:
            reasons.append(
                f"need_more_labels:{int(gate_meta.get('revealed_count') or 0)}/"
                f"{int(gate_meta.get('min_required') or 0)}"
            )
        if gate == LoopGate.FAILED:
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
        if loop.mode not in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION}:
            raise BadRequestAppException("snapshot is only available for active_learning/simulation loop")
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
        return reviewed_ids

    async def _load_selected_sample_ids(
        self,
        *,
        round_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        stmt = (
            select(StepCandidateItem.sample_id)
            .join(Step, Step.id == StepCandidateItem.step_id)
            .where(
                Step.round_id == round_id,
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
        round_id: uuid.UUID,
    ) -> _RevealProbe:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        latest_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        selected_sample_ids = await self._load_selected_sample_ids(round_id=round_id)
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

    @staticmethod
    def _build_wait_user_gate_meta(
        *,
        loop_id: uuid.UUID,
        round_row: Round,
        selected_count: int,
        revealed_count: int,
        missing_count: int,
        min_required: int,
        configured_min_required: int,
    ) -> dict[str, Any]:
        return {
            "round_id": str(round_row.id),
            "round_index": int(round_row.round_index or 0),
            "selected_count": int(selected_count),
            "revealed_count": int(revealed_count),
            "missing_count": int(missing_count),
            "min_required": int(min_required),
            "configured_min_required": int(configured_min_required),
            "annotation_scope": {
                "type": "round_missing_labels",
                "loop_id": str(loop_id),
                "round_id": str(round_row.id),
            },
        }

    async def list_round_missing_samples(
        self,
        *,
        loop_id: uuid.UUID,
        round_id: uuid.UUID,
        current_user_id: uuid.UUID,
        dataset_id: uuid.UUID | None = None,
        q: str | None = None,
        sort_by: str = "createdAt",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 24,
    ) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        round_row = await self.repository.get_by_id_or_raise(round_id)
        if round_row.loop_id != loop_id:
            raise BadRequestAppException("round_id does not belong to loop")

        probe = await self._probe_round_reveal(loop_id=loop_id, round_id=round_id)
        configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
        effective_min_required = self._effective_round_min_required(
            selected_count=probe.selected_count,
            configured_min_required=configured_min_required,
        )

        missing_ids = list(probe.missing_sample_ids or [])
        if not missing_ids:
            return {
                **self._build_wait_user_gate_meta(
                    loop_id=loop_id,
                    round_row=round_row,
                    selected_count=probe.selected_count,
                    revealed_count=probe.revealable_count,
                    missing_count=probe.missing_count,
                    min_required=effective_min_required,
                    configured_min_required=configured_min_required,
                ),
                "loop_id": loop_id,
                "round_id": round_row.id,
                "dataset_stats": [],
                "items": [],
                "total": 0,
                "offset": 0,
                "limit": int(max(1, min(int(limit or 24), 200))),
                "size": 0,
                "has_more": False,
            }

        dataset_stats_stmt = (
            select(Sample.dataset_id, func.count(Sample.id))
            .where(Sample.id.in_(missing_ids))
            .group_by(Sample.dataset_id)
        )
        dataset_stats_rows = list((await self.session.exec(dataset_stats_stmt)).all())
        dataset_name_map: dict[uuid.UUID, str] = {}
        if dataset_stats_rows:
            dataset_ids = [row[0] for row in dataset_stats_rows]
            dataset_rows = list(
                (
                    await self.session.exec(
                        select(Dataset.id, Dataset.name).where(Dataset.id.in_(dataset_ids))
                    )
                ).all()
            )
            dataset_name_map = {dataset_row[0]: str(dataset_row[1] or "") for dataset_row in dataset_rows}
        dataset_stats = [
            {
                "dataset_id": dataset_id_item,
                "dataset_name": dataset_name_map.get(dataset_id_item, ""),
                "count": int(total_count or 0),
            }
            for dataset_id_item, total_count in dataset_stats_rows
        ]
        dataset_stats.sort(key=lambda item: (-int(item["count"]), str(item["dataset_id"])))

        statement = select(Sample).where(Sample.id.in_(missing_ids))
        if dataset_id is not None:
            statement = statement.where(Sample.dataset_id == dataset_id)
        search_text = str(q or "").strip()
        if search_text:
            pattern = f"%{search_text}%"
            statement = statement.where(
                or_(
                    Sample.name.ilike(pattern),
                    Sample.remark.ilike(pattern),
                )
            )

        sort_map = {
            "name": Sample.name,
            "createdAt": Sample.created_at,
            "updatedAt": Sample.updated_at,
            "created_at": Sample.created_at,
            "updated_at": Sample.updated_at,
        }
        sort_column = sort_map.get(str(sort_by or "createdAt"), Sample.created_at)
        order_clause = asc(sort_column) if str(sort_order or "desc").lower() == "asc" else desc(sort_column)
        statement = statement.order_by(order_clause)

        safe_limit = int(max(1, min(int(limit or 24), 200)))
        safe_page = int(max(1, int(page or 1)))
        offset = (safe_page - 1) * safe_limit
        total_stmt = select(func.count()).select_from(statement.subquery())
        total = int((await self.session.scalar(total_stmt)) or 0)
        samples = list((await self.session.exec(statement.offset(offset).limit(safe_limit))).all())

        sample_ids = [sample.id for sample in samples]
        annotation_counts: dict[uuid.UUID, int] = {}
        review_states: dict[uuid.UUID, CommitSampleReviewState] = {}
        if sample_ids and probe.latest_commit_id:
            count_stmt = (
                select(
                    CommitAnnotationMap.sample_id,
                    func.count(CommitAnnotationMap.annotation_id),
                )
                .where(
                    CommitAnnotationMap.commit_id == probe.latest_commit_id,
                    CommitAnnotationMap.sample_id.in_(sample_ids),
                )
                .group_by(CommitAnnotationMap.sample_id)
            )
            count_rows = list((await self.session.exec(count_stmt)).all())
            annotation_counts = {sample_id_item: int(count or 0) for sample_id_item, count in count_rows}

            review_stmt = select(
                CommitSampleState.sample_id,
                CommitSampleState.state,
            ).where(
                CommitSampleState.commit_id == probe.latest_commit_id,
                CommitSampleState.sample_id.in_(sample_ids),
            )
            review_rows = list((await self.session.exec(review_stmt)).all())
            review_states = {sample_id_item: state for sample_id_item, state in review_rows}

        branch_name = "master"
        branch_row = await self.session.exec(select(Branch.name).where(Branch.id == loop.branch_id))
        branch_name_raw = branch_row.first()
        if branch_name_raw:
            branch_name = str(branch_name_raw)

        draft_ids: set[uuid.UUID] = set()
        if sample_ids:
            draft_stmt = select(AnnotationDraft.sample_id).where(
                AnnotationDraft.project_id == loop.project_id,
                AnnotationDraft.user_id == current_user_id,
                AnnotationDraft.branch_name == branch_name,
                AnnotationDraft.sample_id.in_(sample_ids),
            )
            draft_ids = set((await self.session.exec(draft_stmt)).all())

        items: list[dict[str, Any]] = []
        for sample in samples:
            review_state = review_states.get(sample.id)
            items.append(
                {
                    "id": sample.id,
                    "dataset_id": sample.dataset_id,
                    "name": sample.name,
                    "asset_group": sample.asset_group or {},
                    "primary_asset_id": sample.primary_asset_id,
                    "remark": sample.remark,
                    "meta_info": sample.meta_info or {},
                    "created_at": sample.created_at,
                    "updated_at": sample.updated_at,
                    "annotation_count": int(annotation_counts.get(sample.id, 0)),
                    "is_labeled": review_state is not None,
                    "review_state": review_state.value if review_state else "unreviewed",
                    "has_draft": sample.id in draft_ids,
                }
            )

        size = len(items)
        return {
            **self._build_wait_user_gate_meta(
                loop_id=loop_id,
                round_row=round_row,
                selected_count=probe.selected_count,
                revealed_count=probe.revealable_count,
                missing_count=probe.missing_count,
                min_required=effective_min_required,
                configured_min_required=configured_min_required,
            ),
            "loop_id": loop_id,
            "round_id": round_row.id,
            "dataset_stats": dataset_stats,
            "items": items,
            "total": total,
            "offset": offset,
            "limit": safe_limit,
            "size": size,
            "has_more": bool(offset + size < total),
        }

    @transactional
    async def resolve_round_reveal(
        self,
        *,
        loop_id: uuid.UUID,
        round_id: uuid.UUID,
        branch_id: uuid.UUID | None = None,
        force: bool = False,
        min_required: int = 1,
    ) -> dict[str, Any]:
        loop, _snapshot = await self._get_active_snapshot_or_raise(loop_id)
        if branch_id and branch_id != loop.branch_id:
            raise BadRequestAppException("branch_id does not match loop")
        round_row = await self.repository.get_by_id_or_raise(round_id)
        if round_row.loop_id != loop_id:
            raise BadRequestAppException("round_id does not belong to loop")

        probe = await self._probe_round_reveal(loop_id=loop_id, round_id=round_row.id)
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
                    revealed_round_index=int(round_row.round_index),
                    reveal_commit_id=probe.latest_commit_id,
                )
                for sample_id in revealed_ids
            ]
            await self.al_loop_visibility_repo.upsert_rows(rows)

        return {
            "loop_id": loop_id,
            "round_id": round_row.id,
            "round_index": int(round_row.round_index),
            "revealed_count": len(revealed_ids),
            "selected_count": int(probe.selected_count),
            "missing_count": int(probe.missing_count),
            "effective_min_required": int(threshold),
            "latest_commit_id": probe.latest_commit_id,
            "revealable_sample_ids_hash": self._hash_sample_ids(revealed_ids),
        }

    @staticmethod
    def _dedupe_uuid_list(values: list[uuid.UUID]) -> list[uuid.UUID]:
        ordered: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for item in values:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    @staticmethod
    def _selection_candidate_payload(item: StepCandidateItem, rank: int | None = None) -> dict[str, Any]:
        return {
            "sample_id": item.sample_id,
            "rank": int(rank if rank is not None else item.rank),
            "score": float(item.score or 0.0),
            "reason": dict(item.reason or {}),
            "prediction_snapshot": dict(item.prediction_snapshot or {}),
        }

    @staticmethod
    def _sampling_limits_from_round(*, round_row: Round, fallback_topk: int) -> tuple[int, int]:
        resolved_params = round_row.resolved_params if isinstance(round_row.resolved_params, dict) else {}
        sampling = resolved_params.get("sampling") if isinstance(resolved_params.get("sampling"), dict) else {}
        topk = int(sampling.get("topk") or 0)
        if topk <= 0:
            topk = max(1, int(fallback_topk or 1))

        review_pool_size = int(sampling.get("review_pool_size") or 0)
        if review_pool_size <= 0:
            multiplier = int(sampling.get("review_pool_multiplier") or 3)
            multiplier = max(1, multiplier)
            review_pool_size = topk * multiplier
        review_pool_size = max(topk, int(review_pool_size))
        return int(topk), int(review_pool_size)

    async def _resolve_round_selection_context(
        self,
        *,
        round_id: uuid.UUID,
        require_wait_phase: bool,
    ) -> _RoundSelectionContext:
        round_row = await self.repository.get_by_id_or_raise(round_id)
        loop = await self.loop_repo.get_by_id_or_raise(round_row.loop_id)
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("round selection override is only available for active_learning loop")

        if require_wait_phase:
            latest_round = await self.repository.get_latest_by_loop(loop.id)
            if latest_round is None:
                raise BadRequestAppException("loop has no round")
            if latest_round.id != round_row.id:
                raise BadRequestAppException("round selection override only supports latest round attempt")
            if loop.phase != LoopPhase.AL_WAIT_USER:
                raise BadRequestAppException("round selection override requires loop phase al_wait_user")
            if loop.lifecycle not in {LoopLifecycle.RUNNING, LoopLifecycle.PAUSED, LoopLifecycle.STOPPING}:
                raise BadRequestAppException("round selection override requires loop in running/paused/stopping lifecycle")
            if round_row.state != RoundStatus.COMPLETED:
                raise BadRequestAppException("round selection override requires round in completed state")
            if round_row.confirmed_at is not None:
                raise BadRequestAppException("round selection override is locked after round confirm")

        steps = await self.step_repo.list_by_round(round_row.id)
        score_steps = [item for item in steps if item.step_type == StepType.SCORE]
        select_steps = [item for item in steps if item.step_type == StepType.SELECT]
        if not score_steps:
            raise BadRequestAppException("round has no score step")
        if not select_steps:
            raise BadRequestAppException("round has no select step")
        score_step = sorted(score_steps, key=lambda item: int(item.step_index), reverse=True)[0]
        select_step = sorted(select_steps, key=lambda item: int(item.step_index), reverse=True)[0]

        topk, review_pool_size = self._sampling_limits_from_round(round_row=round_row, fallback_topk=loop.query_batch_size)
        score_pool = await self.step_candidate_repo.list_by_step(score_step.id)
        if review_pool_size > 0:
            score_pool = score_pool[:review_pool_size]
        auto_selected = score_pool[:topk]
        return _RoundSelectionContext(
            loop=loop,
            round_row=round_row,
            topk=topk,
            review_pool_size=review_pool_size,
            score_step=score_step,
            select_step=select_step,
            score_pool=score_pool,
            auto_selected=auto_selected,
        )

    @staticmethod
    def _compute_effective_selected_ids(
        *,
        auto_selected_ids: list[uuid.UUID],
        score_pool_ids: list[uuid.UUID],
        include_ids: list[uuid.UUID],
        exclude_ids: set[uuid.UUID],
        topk: int,
    ) -> list[uuid.UUID]:
        result: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()

        for sample_id in auto_selected_ids:
            if sample_id in exclude_ids or sample_id in seen:
                continue
            result.append(sample_id)
            seen.add(sample_id)

        for sample_id in include_ids:
            if sample_id in exclude_ids or sample_id in seen:
                continue
            result.append(sample_id)
            seen.add(sample_id)
            if len(result) >= topk:
                return result[:topk]

        if len(result) < topk:
            for sample_id in score_pool_ids:
                if sample_id in exclude_ids or sample_id in seen:
                    continue
                result.append(sample_id)
                seen.add(sample_id)
                if len(result) >= topk:
                    break
        return result[:topk]

    async def _replace_select_candidates_from_score_pool(
        self,
        *,
        select_step_id: uuid.UUID,
        selected_ids: list[uuid.UUID],
        score_pool_by_id: dict[uuid.UUID, StepCandidateItem],
    ) -> None:
        await self.step_candidate_repo.delete_by_step(select_step_id)
        for rank, sample_id in enumerate(selected_ids, start=1):
            source = score_pool_by_id.get(sample_id)
            if source is None:
                continue
            await self.step_candidate_repo.create(
                {
                    "step_id": select_step_id,
                    "sample_id": sample_id,
                    "rank": rank,
                    "score": float(source.score or 0.0),
                    "reason": dict(source.reason or {}),
                    "prediction_snapshot": dict(source.prediction_snapshot or {}),
                }
            )
        await self.session.flush()

    async def _build_round_selection_payload(
        self,
        *,
        context: _RoundSelectionContext,
    ) -> dict[str, Any]:
        overrides = await self.al_round_selection_override_repo.list_by_round(context.round_row.id)
        include_ids = self._dedupe_uuid_list(
            [item.sample_id for item in overrides if item.op == RoundSelectionOverrideOp.INCLUDE]
        )
        exclude_ids = set(
            self._dedupe_uuid_list([item.sample_id for item in overrides if item.op == RoundSelectionOverrideOp.EXCLUDE])
        )
        score_pool_ids = [item.sample_id for item in context.score_pool]
        effective_ids = self._compute_effective_selected_ids(
            auto_selected_ids=[item.sample_id for item in context.auto_selected],
            score_pool_ids=score_pool_ids,
            include_ids=include_ids,
            exclude_ids=exclude_ids,
            topk=context.topk,
        )
        score_pool_by_id = {item.sample_id: item for item in context.score_pool}

        return {
            "round_id": context.round_row.id,
            "loop_id": context.loop.id,
            "round_index": int(context.round_row.round_index),
            "attempt_index": int(context.round_row.attempt_index),
            "topk": int(context.topk),
            "review_pool_size": int(context.review_pool_size),
            "auto_selected": [
                self._selection_candidate_payload(item, rank=idx + 1) for idx, item in enumerate(context.auto_selected)
            ],
            "score_pool": [self._selection_candidate_payload(item) for item in context.score_pool],
            "overrides": [
                {
                    "sample_id": row.sample_id,
                    "op": row.op,
                    "reason": row.reason,
                }
                for row in overrides
            ],
            "effective_selected": [
                self._selection_candidate_payload(score_pool_by_id[sample_id], rank=idx + 1)
                for idx, sample_id in enumerate(effective_ids)
                if sample_id in score_pool_by_id
            ],
            "selected_count": int(len(effective_ids)),
            "include_count": int(len(include_ids)),
            "exclude_count": int(len(exclude_ids)),
            "_effective_selected_ids": effective_ids,
        }

    async def get_round_selection(self, *, round_id: uuid.UUID) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=False)
        payload = await self._build_round_selection_payload(context=context)
        payload.pop("_effective_selected_ids", None)
        return payload

    @transactional
    async def apply_round_selection_override(
        self,
        *,
        round_id: uuid.UUID,
        include_sample_ids: list[uuid.UUID],
        exclude_sample_ids: list[uuid.UUID],
        actor_user_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=True)
        include_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in include_sample_ids or []])
        exclude_ids = self._dedupe_uuid_list([uuid.UUID(str(item)) for item in exclude_sample_ids or []])
        include_set = set(include_ids)
        exclude_set = set(exclude_ids)
        overlap = include_set & exclude_set
        if overlap:
            raise BadRequestAppException("include_sample_ids and exclude_sample_ids cannot overlap")

        score_pool_ids = {item.sample_id for item in context.score_pool}
        invalid_include = [sample_id for sample_id in include_ids if sample_id not in score_pool_ids]
        if invalid_include:
            preview = ",".join(str(item) for item in invalid_include[:5])
            raise BadRequestAppException(f"include sample is not in score pool: {preview}")

        await self.al_round_selection_override_repo.replace_round_overrides(
            round_id=context.round_row.id,
            include_ids=include_ids,
            exclude_ids=exclude_ids,
            created_by=actor_user_id,
            reason=(str(reason or "").strip() or None),
        )

        payload = await self._build_round_selection_payload(context=context)
        effective_ids = list(payload.get("_effective_selected_ids") or [])
        score_pool_by_id = {item.sample_id: item for item in context.score_pool}
        await self._replace_select_candidates_from_score_pool(
            select_step_id=context.select_step.id,
            selected_ids=effective_ids,
            score_pool_by_id=score_pool_by_id,
        )

        payload.pop("_effective_selected_ids", None)
        return payload

    @transactional
    async def reset_round_selection_override(self, *, round_id: uuid.UUID) -> dict[str, Any]:
        context = await self._resolve_round_selection_context(round_id=round_id, require_wait_phase=True)
        await self.al_round_selection_override_repo.reset_round(context.round_row.id)
        await self._replace_select_candidates_from_score_pool(
            select_step_id=context.select_step.id,
            selected_ids=[item.sample_id for item in context.auto_selected],
            score_pool_by_id={item.sample_id: item for item in context.score_pool},
        )
        payload = await self._build_round_selection_payload(context=context)
        payload.pop("_effective_selected_ids", None)
        return payload

    async def _compute_label_readiness_internal(self, loop_id: uuid.UUID) -> dict[str, Any]:
        loop, snapshot = await self._get_active_snapshot_or_raise(loop_id)
        commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        rows = await self.al_snapshot_sample_repo.list_by_snapshot(snapshot.id)
        partition_map: dict[SnapshotPartition, list[uuid.UUID]] = {}
        for row in rows:
            partition_map.setdefault(row.partition, []).append(row.sample_id)

        seed_ids = partition_map.get(SnapshotPartition.TRAIN_SEED, [])
        val_anchor_ids = list(partition_map.get(SnapshotPartition.VAL_ANCHOR, []))
        test_anchor_ids = list(partition_map.get(SnapshotPartition.TEST_ANCHOR, []))

        labeled_ids: set[uuid.UUID] = set()
        if commit_id:
            check_ids = list({*seed_ids, *val_anchor_ids, *test_anchor_ids})
            labeled_ids = await self._count_labeled_samples(commit_id=commit_id, sample_ids=check_ids)

        def _checkpoint(
            *,
            checkpoint_id: str,
            scope: str,
            round_index: int,
            key: str,
            sample_ids: list[uuid.UUID],
            selected_count: int | None = None,
            revealed_count: int | None = None,
        ) -> dict[str, Any]:
            missing = [sample_id for sample_id in sample_ids if sample_id not in labeled_ids]
            preview = list(missing[:50])
            return {
                "checkpoint_id": checkpoint_id,
                "scope": scope,
                "round_index": int(round_index),
                "key": key,
                "blocking": bool(len(missing) > 0),
                "total": len(sample_ids),
                "missing_count": len(missing),
                "selected_count": selected_count,
                "revealed_count": revealed_count,
                "missing_sample_ids_preview": preview,
                "preview_truncated": len(missing) > len(preview),
            }

        checkpoints: list[dict[str, Any]] = [
            _checkpoint(
                checkpoint_id="r0:seed",
                scope="setup",
                round_index=0,
                key="seed",
                sample_ids=seed_ids,
            ),
            _checkpoint(
                checkpoint_id="r0:val_anchor",
                scope="setup",
                round_index=0,
                key="val_anchor",
                sample_ids=val_anchor_ids,
            ),
            _checkpoint(
                checkpoint_id="r0:test_anchor",
                scope="setup",
                round_index=0,
                key="test_anchor",
                sample_ids=test_anchor_ids,
            ),
        ]

        latest_round = await self.repository.get_latest_by_loop(loop_id)
        if latest_round and int(latest_round.round_index) > 0:
            probe = await self._probe_round_reveal(loop_id=loop_id, round_id=latest_round.id)
            configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
            effective_min_required = self._effective_round_min_required(
                selected_count=probe.selected_count,
                configured_min_required=configured_min_required,
            )
            query_blocking = latest_round.confirmed_at is None and probe.revealable_count < effective_min_required
            preview = list(probe.missing_sample_ids[:50])
            checkpoints.append(
                {
                    "checkpoint_id": f"r{int(latest_round.round_index)}:query",
                    "scope": "round",
                    "round_index": int(latest_round.round_index),
                    "key": "query",
                    "blocking": bool(query_blocking),
                    "total": int(probe.selected_count),
                    "missing_count": int(probe.missing_count),
                    "selected_count": int(probe.selected_count),
                    "revealed_count": int(probe.revealable_count),
                    "missing_sample_ids_preview": preview,
                    "preview_truncated": int(probe.missing_count) > len(preview),
                }
            )

        return {
            "loop_id": loop_id,
            "commit_id": commit_id,
            "checkpoints": checkpoints,
        }

    async def _compute_loop_gate(
        self,
        loop_id: uuid.UUID,
    ) -> tuple[LoopGate, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        read_action = self._action("read", label="Read", runnable=False)
        observe_action = self._action("observe", label="Observe", runnable=False)
        start_action = self._action("start", label="Start")
        lifecycle_text = str(loop.lifecycle.value if hasattr(loop.lifecycle, "value") else loop.lifecycle).strip().lower()
        phase_text = str(loop.phase.value if hasattr(loop.phase, "value") else loop.phase).strip().lower()

        # Terminal lifecycle first.
        if loop.lifecycle == LoopLifecycle.FAILED:
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
                    gate_meta = {
                        "reason": "latest_round_failed",
                        "retry_round_id": str(latest_round.id),
                        "retry_round_index": int(latest_round.round_index),
                        "retry_attempt_index": int(latest_round.attempt_index),
                        "retry_reason_hint": str(latest_round.terminal_reason or ""),
                    }
                    return LoopGate.CAN_RETRY, gate_meta, retry_action, [retry_action, read_action]
            return LoopGate.FAILED, {"reason": "terminal"}, None, [read_action]
        if loop.lifecycle == LoopLifecycle.COMPLETED:
            return LoopGate.COMPLETED, {"reason": "terminal"}, None, [read_action]
        if loop.lifecycle == LoopLifecycle.STOPPED:
            return LoopGate.STOPPED, {"reason": "terminal"}, None, [read_action]

        # Running lifecycle gates: running/paused/stopping are explicit and never
        # downgraded by setup checks such as snapshot/gap.
        if loop.lifecycle == LoopLifecycle.PAUSED:
            return LoopGate.PAUSED, {"phase": phase_text}, None, [observe_action]
        if loop.lifecycle == LoopLifecycle.STOPPING:
            return LoopGate.STOPPING, {"phase": phase_text}, None, [observe_action]
        if loop.lifecycle == LoopLifecycle.RUNNING:
            if loop.mode == LoopMode.MANUAL:
                if phase_text != LoopPhase.MANUAL_EVAL.value:
                    return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

                latest_round = await self.repository.get_latest_by_loop(loop_id)
                if latest_round and latest_round.state == RoundStatus.COMPLETED:
                    round_index = int(latest_round.round_index or 0)
                    if round_index < int(loop.max_rounds or 1):
                        start_next_round_action = self._action("start_next_round", label="Start Next Round")
                        return (
                            LoopGate.CAN_NEXT_ROUND,
                            {
                                "round_index": round_index,
                                "attempt_index": int(latest_round.attempt_index or 1),
                            },
                            start_next_round_action,
                            [start_next_round_action],
                        )
                return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

            if loop.mode == LoopMode.SIMULATION:
                return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

            if phase_text != LoopPhase.AL_WAIT_USER.value:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]

            latest_round = await self.repository.get_latest_by_loop(loop_id)
            if latest_round is None:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]
            if latest_round.state != RoundStatus.COMPLETED:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]
            configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
            if latest_round.confirmed_at is not None:
                start_next_round_action = self._action("start_next_round", label="Start Next Round")
                confirmed_selected_count = int(latest_round.confirmed_selected_count or 0)
                confirmed_revealed_count = int(latest_round.confirmed_revealed_count or 0)
                confirmed_effective_min_required = int(
                    latest_round.confirmed_effective_min_required
                    or self._effective_round_min_required(
                        selected_count=confirmed_selected_count,
                        configured_min_required=configured_min_required,
                    )
                )
                gate_meta = self._build_wait_user_gate_meta(
                    loop_id=loop_id,
                    round_row=latest_round,
                    selected_count=confirmed_selected_count,
                    revealed_count=confirmed_revealed_count,
                    missing_count=max(0, confirmed_selected_count - confirmed_revealed_count),
                    min_required=confirmed_effective_min_required,
                    configured_min_required=configured_min_required,
                )
                gate_meta.update(
                    {
                        "attempt_index": int(latest_round.attempt_index or 1),
                        "confirmed_at": latest_round.confirmed_at.isoformat() if latest_round.confirmed_at else None,
                        "confirmed_revealed_count": confirmed_revealed_count,
                        "confirmed_selected_count": confirmed_selected_count,
                        "confirmed_effective_min_required": confirmed_effective_min_required,
                    }
                )
                return (
                    LoopGate.CAN_NEXT_ROUND,
                    gate_meta,
                    start_next_round_action,
                    [start_next_round_action],
                )

            probe = await self._probe_round_reveal(loop_id=loop_id, round_id=latest_round.id)
            effective_min_required = self._effective_round_min_required(
                selected_count=probe.selected_count,
                configured_min_required=configured_min_required,
            )
            gate_meta = self._build_wait_user_gate_meta(
                loop_id=loop_id,
                round_row=latest_round,
                selected_count=probe.selected_count,
                revealed_count=probe.revealable_count,
                missing_count=probe.missing_count,
                min_required=effective_min_required,
                configured_min_required=configured_min_required,
            )
            if effective_min_required <= 0 or probe.revealable_count >= effective_min_required:
                confirm_action = self._action("confirm", label="Confirm Reveal")
                selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
                return (
                    LoopGate.CAN_CONFIRM,
                    gate_meta,
                    confirm_action,
                    [confirm_action, selection_adjust_action],
                )
            annotate_action = self._action("annotate", label="Annotate Query Samples")
            selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
            return (
                LoopGate.NEED_ROUND_LABELS,
                gate_meta,
                annotate_action,
                [annotate_action, selection_adjust_action],
            )

        # Draft/setup gates.
        if loop.lifecycle == LoopLifecycle.DRAFT:
            if loop.mode == LoopMode.MANUAL:
                return LoopGate.CAN_START, {"mode": str(loop.mode)}, start_action, [start_action]

            if not loop.active_snapshot_version_id:
                snapshot_action = self._action("snapshot_init", label="Init Snapshot")
                return LoopGate.NEED_SNAPSHOT, {"missing": "snapshot"}, snapshot_action, [snapshot_action, read_action]
            return LoopGate.CAN_START, {"mode": str(loop.mode)}, start_action, [start_action]

        # Safety fallback for unexpected lifecycle values.
        return LoopGate.CAN_START, {"phase": phase_text}, start_action, [start_action]

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
            candidate_ids = list({uuid.UUID(str(item)) for item in sample_ids_payload})
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
        gate, _gate_meta, _primary_action, _actions = await self._compute_loop_gate(loop.id)
        return {
            "loop_id": loop.id,
            "gate": gate,
            "active_snapshot_version_id": snapshot.id,
            "version_index": version_index,
            "created": True,
            "sample_count": len(merged_rows),
        }

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

    async def get_loop_gate(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        gate, gate_meta, primary_action, gate_actions = await self._compute_loop_gate(loop_id)
        actions = self._merge_gate_actions(loop=loop, gate=gate, actions=gate_actions)
        latest_round = await self.repository.get_latest_by_loop(loop_id)
        branch_head_commit_id = await self._get_branch_head_commit_id(loop.branch_id)
        token_payload = self._decision_token_payload(
            loop=loop,
            gate=gate,
            gate_meta=gate_meta,
            actions=actions,
            latest_round=latest_round,
            branch_head_commit_id=branch_head_commit_id,
        )
        decision_token = self._make_decision_token(token_payload)
        blocking_reasons = self._build_blocking_reasons(
            gate=gate,
            gate_meta=gate_meta,
            primary_action=primary_action,
        )
        return {
            "loop_id": loop_id,
            "gate": gate,
            "gate_meta": gate_meta,
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
        decision = await self.get_loop_gate(loop_id=loop_id)
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
            raise BadRequestAppException("no actionable transition for current gate")

        actions = decision.get("actions") or []
        matched = None
        for item in actions:
            key = str((item or {}).get("key") or "").strip().lower()
            if key == action_key:
                matched = item
                break
        if matched is None:
            raise BadRequestAppException(f"action not allowed in current gate: {action_key}")
        if not bool(matched.get("runnable", True)):
            raise BadRequestAppException(f"action is not runnable in current gate: {action_key}")
        return decision, action_key, matched

    async def get_loop_label_readiness(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        payload = await self._compute_label_readiness_internal(loop_id)
        gate_payload = await self.get_loop_gate(loop_id=loop_id)
        checkpoints = list(payload.get("checkpoints") or [])
        active_checkpoint_id: str | None = None
        gate = gate_payload.get("gate")

        if gate == LoopGate.NEED_LABELS:
            for item in checkpoints:
                if item.get("scope") == "setup" and bool(item.get("blocking")):
                    active_checkpoint_id = str(item.get("checkpoint_id") or "")
                    break
        elif gate in {LoopGate.NEED_ROUND_LABELS, LoopGate.CAN_CONFIRM, LoopGate.CAN_NEXT_ROUND}:
            for item in checkpoints:
                if item.get("key") == "query":
                    active_checkpoint_id = str(item.get("checkpoint_id") or "")
                    break
        if not active_checkpoint_id:
            for item in checkpoints:
                if bool(item.get("blocking")):
                    active_checkpoint_id = str(item.get("checkpoint_id") or "")
                    break

        payload["active_checkpoint_id"] = active_checkpoint_id
        return payload

    async def _resolve_prediction_source_step(
        self,
        *,
        loop_id: uuid.UUID,
        source_round_id: uuid.UUID | None,
        source_step_id: uuid.UUID | None,
    ) -> tuple[Round, Step]:
        if source_step_id is not None:
            step_row = await self.step_repo.get_by_id_or_raise(source_step_id)
            round_row = await self.repository.get_by_id_or_raise(step_row.round_id)
            if round_row.loop_id != loop_id:
                raise BadRequestAppException("source_step_id does not belong to loop")
            return round_row, step_row

        if source_round_id is not None:
            round_row = await self.repository.get_by_id_or_raise(source_round_id)
            if round_row.loop_id != loop_id:
                raise BadRequestAppException("source_round_id does not belong to loop")
        else:
            round_row = await self.repository.get_latest_by_loop(loop_id)
            if round_row is None:
                raise BadRequestAppException("loop has no round")

        steps = await self.step_repo.list_by_round(round_row.id)
        ordered = sorted(steps, key=lambda item: int(item.step_index or 0), reverse=True)
        preferred = next((item for item in ordered if item.step_type == StepType.SCORE), None)
        if preferred is None:
            preferred = next((item for item in ordered if item.step_type == StepType.PREDICT), None)
        if preferred is None:
            preferred = next((item for item in ordered if item.step_type == StepType.SELECT), None)
        if preferred is None:
            raise BadRequestAppException("round has no score/predict/select step for prediction_set source")
        return round_row, preferred

    @transactional
    async def generate_prediction_set(
        self,
        *,
        loop_id: uuid.UUID,
        payload: dict[str, Any],
        actor_user_id: uuid.UUID | None,
    ) -> PredictionSet:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        source_round_raw = payload.get("source_round_id")
        source_step_raw = payload.get("source_step_id")
        source_round_id = uuid.UUID(str(source_round_raw)) if source_round_raw else None
        source_step_id = uuid.UUID(str(source_step_raw)) if source_step_raw else None
        source_round, source_step = await self._resolve_prediction_source_step(
            loop_id=loop_id,
            source_round_id=source_round_id,
            source_step_id=source_step_id,
        )

        scope_type = str(payload.get("scope_type") or "snapshot_scope").strip() or "snapshot_scope"
        scope_payload = payload.get("scope_payload") if isinstance(payload.get("scope_payload"), dict) else {}
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

        base_commit_raw = payload.get("base_commit_id")
        base_commit_id: uuid.UUID | None = None
        if base_commit_raw:
            base_commit_id = uuid.UUID(str(base_commit_raw))
        elif source_round.input_commit_id:
            base_commit_id = source_round.input_commit_id

        model_id_raw = payload.get("model_id")
        model_id: uuid.UUID | None = uuid.UUID(str(model_id_raw)) if model_id_raw else None

        prediction_set = await self.prediction_set_repo.create(
            {
                "loop_id": loop_id,
                "source_round_id": source_round.id,
                "source_step_id": source_step.id,
                "model_id": model_id,
                "base_commit_id": base_commit_id,
                "scope_type": scope_type,
                "scope_payload": scope_payload,
                "status": "generating",
                "total_items": 0,
                "params": params,
                "created_by": actor_user_id,
            }
        )

        source_candidates = await self.step_candidate_repo.list_by_step(source_step.id)
        prediction_rows: list[dict[str, Any]] = []
        for candidate in source_candidates:
            snapshot = dict(candidate.prediction_snapshot or {})
            label_raw = snapshot.get("label_id") or snapshot.get("labelId")
            label_id: uuid.UUID | None = None
            if label_raw:
                try:
                    label_id = uuid.UUID(str(label_raw))
                except Exception:
                    label_id = None
            prediction_rows.append(
                {
                    "sample_id": candidate.sample_id,
                    "rank": int(candidate.rank or 0),
                    "score": float(candidate.score or 0.0),
                    "label_id": label_id,
                    "geometry": snapshot.get("geometry") if isinstance(snapshot.get("geometry"), dict) else {},
                    "attrs": snapshot.get("attrs") if isinstance(snapshot.get("attrs"), dict) else {},
                    "confidence": float(snapshot.get("confidence") or candidate.score or 0.0),
                    "meta": snapshot if isinstance(snapshot, dict) else {},
                }
            )

        await self.prediction_item_repo.replace_rows(
            prediction_set_id=prediction_set.id,
            rows=prediction_rows,
        )
        prediction_set = await self.prediction_set_repo.update(
            prediction_set.id,
            {
                "status": "ready",
                "total_items": int(len(prediction_rows)),
            },
        )
        if prediction_set is None:
            raise BadRequestAppException("failed to persist generated prediction_set")
        return prediction_set

    async def list_prediction_sets(self, *, loop_id: uuid.UUID, limit: int = 100) -> list[PredictionSet]:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        return await self.prediction_set_repo.list_by_loop(loop_id=loop_id, limit=limit)

    async def get_prediction_set_detail(
        self,
        *,
        prediction_set_id: uuid.UUID,
        item_limit: int = 2000,
    ) -> tuple[PredictionSet, list[PredictionItem]]:
        prediction_set = await self.prediction_set_repo.get_by_id_or_raise(prediction_set_id)
        items = await self.prediction_item_repo.list_by_prediction_set(prediction_set_id, limit=item_limit)
        return prediction_set, items

    @transactional
    async def apply_prediction_set(
        self,
        *,
        prediction_set_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        branch_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if actor_user_id is None:
            raise BadRequestAppException("actor user is required when applying prediction_set")
        prediction_set = await self.prediction_set_repo.get_by_id_or_raise(prediction_set_id)
        loop = await self.loop_repo.get_by_id_or_raise(prediction_set.loop_id)
        items = await self.prediction_item_repo.list_by_prediction_set(prediction_set_id, limit=100000)
        if not items:
            return {
                "prediction_set_id": prediction_set.id,
                "applied_count": 0,
                "status": str(prediction_set.status or "ready"),
            }

        resolved_branch_name = str(branch_name or "").strip()
        if not resolved_branch_name:
            branch = await self.session.get(Branch, loop.branch_id)
            resolved_branch_name = str(getattr(branch, "name", "") or "").strip() or "master"

        applied_count = 0
        if not dry_run:
            draft_repo = AnnotationDraftRepository(self.session)
            grouped_items: dict[uuid.UUID, list[PredictionItem]] = {}
            for item in items:
                grouped_items.setdefault(item.sample_id, []).append(item)
            for sample_id, group in grouped_items.items():
                existing = await draft_repo.get_by_unique(
                    project_id=loop.project_id,
                    sample_id=sample_id,
                    user_id=actor_user_id,
                    branch_name=resolved_branch_name,
                )
                existing_payload = dict(existing.payload or {}) if existing and isinstance(existing.payload, dict) else {}
                existing_annotations = existing_payload.get("annotations")
                base_annotations = [
                    ann
                    for ann in (existing_annotations if isinstance(existing_annotations, list) else [])
                    if str(ann.get("source") or "").strip().lower() != "model"
                ]

                model_annotations: list[dict[str, Any]] = []
                for item in sorted(group, key=lambda row: int(row.rank or 0)):
                    if item.label_id is None:
                        continue
                    model_annotations.append(
                        {
                            "id": str(uuid.uuid4()),
                            "project_id": str(loop.project_id),
                            "sample_id": str(sample_id),
                            "label_id": str(item.label_id),
                            "geometry": dict(item.geometry or {}),
                            "attrs": dict(item.attrs or {}),
                            "source": "model",
                            "confidence": float(item.confidence or 0.0),
                            "annotator_id": str(actor_user_id),
                        }
                    )
                if not model_annotations:
                    continue
                applied_count += len(model_annotations)
                payload_to_write = {
                    **existing_payload,
                    "annotations": base_annotations + model_annotations,
                }
                if existing is None:
                    await draft_repo.create(
                        {
                            "project_id": loop.project_id,
                            "sample_id": sample_id,
                            "user_id": actor_user_id,
                            "branch_name": resolved_branch_name,
                            "payload": payload_to_write,
                        }
                    )
                else:
                    await draft_repo.update(existing.id, {"payload": payload_to_write})
            prediction_set = await self.prediction_set_repo.update(
                prediction_set.id,
                {
                    "status": "applied",
                },
            ) or prediction_set

        return {
            "prediction_set_id": prediction_set.id,
            "applied_count": int(applied_count if not dry_run else len(items)),
            "status": str(prediction_set.status or ("ready" if dry_run else "applied")),
        }
