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

from sqlalchemy import distinct
from sqlmodel import select

from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.exceptions import ConflictAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.project import ProjectDataset
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

        latest_round = await self.repository.get_latest_by_loop(loop.id)
        if latest_round is None:
            raise BadRequestAppException("loop has no round")
        if latest_round.id != round_row.id:
            raise BadRequestAppException("round selection override only supports latest round attempt")

        if require_wait_phase:
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
            probe = await self._probe_round_reveal(loop_id=loop_id, round_id=latest_round.id)
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
            if loop.mode != LoopMode.ACTIVE_LEARNING:
                return LoopGate.RUNNING, {"mode": str(loop.mode), "phase": phase_text}, None, [observe_action]

            if phase_text != LoopPhase.AL_WAIT_USER.value:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]

            latest_round = await self.repository.get_latest_by_loop(loop_id)
            round_index = int(latest_round.round_index) if latest_round else 0
            if round_index <= 0:
                annotate_action = self._action("annotate", label="Annotate Query Samples", runnable=False)
                selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
                return (
                    LoopGate.NEED_ROUND_LABELS,
                    {"round_index": 0, "revealed_count": 0},
                    annotate_action,
                    [annotate_action, selection_adjust_action],
                )
            if latest_round.state != RoundStatus.COMPLETED:
                return LoopGate.RUNNING, {"phase": phase_text}, None, [observe_action]
            if latest_round.confirmed_at is not None:
                start_next_round_action = self._action("start_next_round", label="Start Next Round")
                return (
                    LoopGate.CAN_NEXT_ROUND,
                    {
                        "round_index": round_index,
                        "attempt_index": int(latest_round.attempt_index),
                        "confirmed_at": latest_round.confirmed_at.isoformat() if latest_round.confirmed_at else None,
                        "confirmed_revealed_count": int(latest_round.confirmed_revealed_count or 0),
                        "confirmed_selected_count": int(latest_round.confirmed_selected_count or 0),
                        "confirmed_effective_min_required": int(latest_round.confirmed_effective_min_required or 0),
                    },
                    start_next_round_action,
                    [start_next_round_action],
                )

            probe = await self._probe_round_reveal(loop_id=loop_id, round_id=latest_round.id)
            configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
            effective_min_required = self._effective_round_min_required(
                selected_count=probe.selected_count,
                configured_min_required=configured_min_required,
            )
            if probe.revealable_count >= effective_min_required:
                confirm_action = self._action("confirm", label="Confirm Reveal")
                selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
                return (
                    LoopGate.CAN_CONFIRM,
                    {
                        "round_index": round_index,
                        "revealed_count": probe.revealable_count,
                        "selected_count": probe.selected_count,
                        "missing_count": probe.missing_count,
                        "min_required": effective_min_required,
                        "configured_min_required": configured_min_required,
                    },
                    confirm_action,
                    [confirm_action, selection_adjust_action],
                )
            annotate_action = self._action("annotate", label="Annotate Query Samples", runnable=False)
            selection_adjust_action = self._action("selection_adjust", label="Adjust TopK Selection")
            return (
                LoopGate.NEED_ROUND_LABELS,
                {
                    "round_index": round_index,
                    "revealed_count": probe.revealable_count,
                    "selected_count": probe.selected_count,
                    "missing_count": probe.missing_count,
                    "min_required": effective_min_required,
                    "configured_min_required": configured_min_required,
                },
                annotate_action,
                [annotate_action, selection_adjust_action],
            )

        # Draft/setup gates.
        if loop.lifecycle == LoopLifecycle.DRAFT:
            if loop.mode != LoopMode.ACTIVE_LEARNING:
                return LoopGate.CAN_START, {"mode": str(loop.mode)}, start_action, [start_action]

            if not loop.active_snapshot_version_id:
                snapshot_action = self._action("snapshot_init", label="Init Snapshot")
                return LoopGate.NEED_SNAPSHOT, {"missing": "snapshot"}, snapshot_action, [snapshot_action, read_action]

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
                return LoopGate.NEED_LABELS, {"gap_count": gap_total}, gap_action, [gap_action, read_action]
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
        if loop.mode != LoopMode.ACTIVE_LEARNING:
            raise BadRequestAppException("snapshot is only available for active_learning loop")
        history = await self.al_snapshot_version_repo.list_by_loop(loop_id)
        active = None
        if loop.active_snapshot_version_id:
            active = await self.al_snapshot_version_repo.get_by_id(loop.active_snapshot_version_id)
        frozen_partition_counts: dict[str, int] = {}
        virtual_visibility_counts: dict[str, int] = {}
        effective_split_counts: dict[str, int] = {}
        if active:
            rows = await self.al_snapshot_sample_repo.list_by_snapshot(active.id)
            counter = Counter([str(row.partition.value if hasattr(row.partition, "value") else row.partition) for row in rows])
            frozen_partition_counts = {key: int(value) for key, value in counter.items()}

            partition_by_sample_id: dict[uuid.UUID, SnapshotPartition] = {row.sample_id: row.partition for row in rows}
            visible_sample_ids = set(await self.al_loop_visibility_repo.list_visible_sample_ids(loop_id))
            train_visible_total = int(len(visible_sample_ids))
            train_visible_seed = int(
                sum(
                    1
                    for sample_id in visible_sample_ids
                    if partition_by_sample_id.get(sample_id) == SnapshotPartition.TRAIN_SEED
                )
            )
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
            virtual_visibility_counts = {
                "train_visible_total": train_visible_total,
                "train_visible_seed": train_visible_seed,
                "train_visible_revealed_from_pool": train_visible_revealed_from_pool,
                "train_pool_hidden": int(train_pool_hidden),
            }

            val_effective = int(counter.get(SnapshotPartition.VAL_ANCHOR.value, 0))
            if active.val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
                val_effective += int(counter.get(SnapshotPartition.VAL_BATCH.value, 0))
            test_effective = int(counter.get(SnapshotPartition.TEST_ANCHOR.value, 0)) + int(
                counter.get(SnapshotPartition.TEST_BATCH.value, 0)
            )
            effective_split_counts = {
                "train_effective": train_visible_total,
                "val_effective": int(val_effective),
                "test_effective": int(test_effective),
            }
        return {
            "loop_id": loop.id,
            "active_snapshot_version_id": loop.active_snapshot_version_id,
            "active": active,
            "history": history,
            "frozen_partition_counts": frozen_partition_counts,
            "virtual_visibility_counts": virtual_visibility_counts,
            "effective_split_counts": effective_split_counts,
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

    async def get_loop_annotation_gaps(self, *, loop_id: uuid.UUID) -> dict[str, Any]:
        return await self._compute_annotation_gaps_internal(loop_id)
