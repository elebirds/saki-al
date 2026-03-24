"""Snapshot policy/utility mixin."""

from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.runtime.domain.model_class_schema import ModelClassSchema
from saki_api.modules.runtime.domain.prediction import Prediction
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.service.runtime_service.prediction_label_resolver import PredictionResolveError
from saki_api.modules.shared.modeling.enums import (
    CommitSampleReviewState,
    LoopGate,
    LoopLifecycle,
    LoopMode,
    RoundStatus,
    SnapshotPartition,
    SnapshotUpdateMode,
    SnapshotValPolicy,
)


@dataclass(slots=True)
class _RevealProbe:
    selected_count: int
    revealable_count: int
    missing_count: int
    missing_sample_ids: list[uuid.UUID]
    revealable_sample_ids: list[uuid.UUID]
    latest_commit_id: uuid.UUID | None


@dataclass(slots=True)
class _SnapshotTrainStats:
    pool_hidden: int
    train_visible: int
    total_train_universe: int


@dataclass(slots=True)
class _RoundSelectionContext:
    loop: Any
    round_row: Round
    topk: int
    review_pool_size: int
    score_step: Step
    select_step: Step
    score_pool: list[TaskCandidateItem]
    auto_selected: list[TaskCandidateItem]


class SnapshotPolicyMixin:
    _PATCH_GROUP_PATTERN = re.compile(r"^(?P<origin>.+?)__-?\d+__-?\d+___-?\d+(?:\.[^.]+)?$")

    @staticmethod
    def _effective_round_min_required(*, selected_count: int, configured_min_required: int) -> int:
        del configured_min_required
        selected = max(0, int(selected_count or 0))
        if selected <= 0:
            return 0
        return selected

    def _resolve_snapshot_seed(self, *, loop: Any) -> str:
        seed = self._get_loop_global_seed(loop.config or {})
        if seed:
            return seed
        raise BadRequestAppException("config.reproducibility.global_seed is required for snapshot")

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
            "loop_lifecycle": SnapshotPolicyMixin._enum_text(loop.lifecycle),
            "loop_phase": SnapshotPolicyMixin._enum_text(loop.phase),
            "loop_mode": SnapshotPolicyMixin._enum_text(loop.mode),
            "active_snapshot_version_id": str(loop.active_snapshot_version_id or ""),
            "gate": SnapshotPolicyMixin._enum_text(gate),
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
                "state": SnapshotPolicyMixin._enum_text(getattr(latest_round, "state", "") or ""),
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
            LoopGate.PAUSING,
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
            elif lifecycle_text == LoopLifecycle.PAUSING.value:
                _append(self._action("observe", label="Observe", runnable=False))
            elif lifecycle_text == LoopLifecycle.STOPPING.value:
                _append(self._action("observe", label="Observe", runnable=False))

        if (
            loop.mode == LoopMode.ACTIVE_LEARNING
            and loop.active_snapshot_version_id
            and gate
            in {
                LoopGate.CAN_START,
                LoopGate.RUNNING,
                LoopGate.PAUSING,
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

    @staticmethod
    def _compute_snapshot_train_stats(
        *,
        rows: list[ALSnapshotSample],
        visible_sample_ids: set[uuid.UUID],
    ) -> _SnapshotTrainStats:
        train_pool_sample_ids: set[uuid.UUID] = set()
        total_train_sample_ids: set[uuid.UUID] = set()
        for row in rows:
            if row.partition == SnapshotPartition.TRAIN_POOL:
                train_pool_sample_ids.add(row.sample_id)
                total_train_sample_ids.add(row.sample_id)
                continue
            if row.partition == SnapshotPartition.TRAIN_SEED:
                total_train_sample_ids.add(row.sample_id)
        train_visible = int(len(total_train_sample_ids & visible_sample_ids))
        pool_hidden = int(len(train_pool_sample_ids - visible_sample_ids))
        return _SnapshotTrainStats(
            pool_hidden=pool_hidden,
            train_visible=train_visible,
            total_train_universe=int(len(total_train_sample_ids)),
        )

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
    def _normalize_sample_records(
        *,
        sample_ids: list[uuid.UUID],
        sample_records: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        if sample_records:
            for record in sample_records:
                sample_id = SnapshotPolicyMixin._safe_uuid(record.get("sample_id") or record.get("id"))
                if sample_id is None or sample_id in seen:
                    continue
                seen.add(sample_id)
                meta_info = record.get("meta_info") if isinstance(record.get("meta_info"), dict) else {}
                normalized.append(
                    {
                        "sample_id": sample_id,
                        "name": str(record.get("name") or "").strip(),
                        "meta_info": dict(meta_info),
                    }
                )
            return normalized

        for sample_id in SnapshotPolicyMixin._dedupe_uuid_list(sample_ids):
            if sample_id in seen:
                continue
            seen.add(sample_id)
            normalized.append(
                {
                    "sample_id": sample_id,
                    "name": "",
                    "meta_info": {},
                }
            )
        return normalized

    @staticmethod
    def _extract_patch_origin(raw: Any) -> str | None:
        text = str(raw or "").strip().replace("\\", "/")
        if not text:
            return None
        filename = text.rsplit("/", 1)[-1]
        match = SnapshotPolicyMixin._PATCH_GROUP_PATTERN.match(filename)
        if not match:
            return None
        origin = str(match.group("origin") or "").strip()
        return origin or None

    @staticmethod
    def _sample_group_key(record: dict[str, Any]) -> str:
        meta_info = record.get("meta_info") if isinstance(record.get("meta_info"), dict) else {}
        original_relative_path = meta_info.get("original_relative_path")
        origin = SnapshotPolicyMixin._extract_patch_origin(original_relative_path)
        if origin:
            return origin
        origin = SnapshotPolicyMixin._extract_patch_origin(record.get("name"))
        if origin:
            return origin
        return str(record["sample_id"])

    @staticmethod
    def _group_sample_records(
        *,
        sample_ids: list[uuid.UUID],
        sample_records: list[dict[str, Any]] | None,
    ) -> list[tuple[str, list[uuid.UUID]]]:
        records = SnapshotPolicyMixin._normalize_sample_records(
            sample_ids=sample_ids,
            sample_records=sample_records,
        )
        grouped: dict[str, list[uuid.UUID]] = {}
        for record in records:
            grouped.setdefault(SnapshotPolicyMixin._sample_group_key(record), []).append(record["sample_id"])
        return [
            (group_key, sorted(group_sample_ids, key=lambda item: str(item)))
            for group_key, group_sample_ids in sorted(grouped.items(), key=lambda item: item[0])
        ]

    @staticmethod
    def _shuffle_grouped_sample_ids(
        *,
        sample_ids: list[uuid.UUID],
        sample_records: list[dict[str, Any]] | None,
        seed: str,
    ) -> list[list[uuid.UUID]]:
        grouped = SnapshotPolicyMixin._group_sample_records(
            sample_ids=sample_ids,
            sample_records=sample_records,
        )
        randomizer = random.Random(seed)
        randomizer.shuffle(grouped)
        return [group_sample_ids for _group_key, group_sample_ids in grouped]

    @staticmethod
    def _take_group_slice(
        *,
        grouped_sample_ids: list[list[uuid.UUID]],
        target_count: int,
    ) -> tuple[list[uuid.UUID], list[list[uuid.UUID]]]:
        if target_count <= 0 or not grouped_sample_ids:
            return [], list(grouped_sample_ids)

        selected: list[uuid.UUID] = []
        selected_count = 0
        index = 0
        while index < len(grouped_sample_ids) and selected_count < target_count:
            group_sample_ids = grouped_sample_ids[index]
            selected.extend(group_sample_ids)
            selected_count += len(group_sample_ids)
            index += 1
        return selected, list(grouped_sample_ids[index:])

    @staticmethod
    def _assign_init_partitions(
        *,
        sample_ids: list[uuid.UUID],
        sample_records: list[dict[str, Any]] | None = None,
        seed: str,
        test_ratio: float,
        val_ratio: float,
        train_seed_ratio: float,
    ) -> list[dict[str, Any]]:
        grouped_sample_ids = SnapshotPolicyMixin._shuffle_grouped_sample_ids(
            sample_ids=sample_ids,
            sample_records=sample_records,
            seed=seed,
        )
        total = sum(len(group_sample_ids) for group_sample_ids in grouped_sample_ids)
        test_count, val_count, train_seed_count = SnapshotPolicyMixin._allocate_counts(
            total=total,
            test_ratio=test_ratio,
            val_ratio=val_ratio,
            train_seed_ratio=train_seed_ratio,
        )
        test_ids, grouped_sample_ids = SnapshotPolicyMixin._take_group_slice(
            grouped_sample_ids=grouped_sample_ids,
            target_count=test_count,
        )
        val_ids, grouped_sample_ids = SnapshotPolicyMixin._take_group_slice(
            grouped_sample_ids=grouped_sample_ids,
            target_count=val_count,
        )
        seed_ids, grouped_sample_ids = SnapshotPolicyMixin._take_group_slice(
            grouped_sample_ids=grouped_sample_ids,
            target_count=train_seed_count,
        )
        pool_ids = [sample_id for group_sample_ids in grouped_sample_ids for sample_id in group_sample_ids]

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
        sample_records: list[dict[str, Any]] | None = None,
        seed: str,
        cohort_index: int,
        test_ratio: float,
        val_ratio: float,
        val_policy: SnapshotValPolicy,
    ) -> list[dict[str, Any]]:
        grouped_sample_ids = SnapshotPolicyMixin._shuffle_grouped_sample_ids(
            sample_ids=sample_ids,
            sample_records=sample_records,
            seed=seed,
        )
        total = sum(len(group_sample_ids) for group_sample_ids in grouped_sample_ids)
        test_count = max(0, min(total, int(round(total * test_ratio))))
        val_count = 0
        if val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
            val_count = max(0, min(total - test_count, int(round(total * val_ratio))))
        while test_count + val_count > total:
            if val_count > 0:
                val_count -= 1
            else:
                test_count -= 1
        test_ids, grouped_sample_ids = SnapshotPolicyMixin._take_group_slice(
            grouped_sample_ids=grouped_sample_ids,
            target_count=test_count,
        )
        val_ids, grouped_sample_ids = SnapshotPolicyMixin._take_group_slice(
            grouped_sample_ids=grouped_sample_ids,
            target_count=val_count,
        )
        pool_ids = [sample_id for group_sample_ids in grouped_sample_ids for sample_id in group_sample_ids]

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
    def _selection_candidate_payload(item: TaskCandidateItem, rank: int | None = None) -> dict[str, Any]:
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

    @staticmethod
    def _safe_uuid(raw: Any) -> uuid.UUID | None:
        if raw is None:
            return None
        try:
            return uuid.UUID(str(raw))
        except Exception:
            return None

    @staticmethod
    def _safe_float(raw: Any, *, default: float = 0.0) -> float:
        try:
            return float(raw)
        except Exception:
            return float(default)

    @staticmethod
    def _prediction_entries_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(snapshot, dict):
            return []
        for key in ("base_predictions", "predictions"):
            rows = snapshot.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        return []

    @staticmethod
    def _normalize_class_name(raw: Any) -> str:
        text = str(raw or "").strip().lower()
        return " ".join(text.split())

    @staticmethod
    def _hash_model_class_schema(rows: list[ModelClassSchema]) -> str:
        payload = [
            {
                "class_index": int(item.class_index),
                "label_id": str(item.label_id),
                "class_name_norm": str(item.class_name_norm or ""),
            }
            for item in rows
        ]
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _attach_task_projection(prediction: Prediction, step: Step | None) -> Prediction:
        del step
        return prediction
