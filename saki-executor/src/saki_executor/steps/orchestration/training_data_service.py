from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import TaskExecutionRequest
from saki_executor.steps.services import IRDatasetBuildReport, build_training_batch_ir
from saki_plugin_sdk import TaskRuntimeContext, resolve_train_val_split
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb

FetchAllFn = Callable[[str, str, str, str], Awaitable[list[dict[str, Any]]]]
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class TrainingDataBundle:
    labels: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    train_annotations: list[dict[str, Any]]
    ir_batch: irpb.DataBatchIR
    ir_report: IRDatasetBuildReport
    protected: set[str]
    splits: dict[str, list[dict[str, Any]]]


class TrainingDataService:
    def __init__(
        self,
        *,
        fetch_all: FetchAllFn,
        cache: AssetCache,
        stop_event: asyncio.Event,
    ) -> None:
        self._fetch_all = fetch_all
        self._cache = cache
        self._stop_event = stop_event

    async def prepare(
        self,
        *,
        request: TaskExecutionRequest,
        plugin_params: dict[str, Any],
        runtime_context: TaskRuntimeContext,
        emit: EmitFn,
    ) -> TrainingDataBundle:
        labels = await self._fetch_all(
            request.task_id,
            "labels",
            request.project_id,
            request.input_commit_id,
        )
        samples = await self._fetch_all(
            request.task_id,
            "samples",
            request.project_id,
            request.input_commit_id,
        )
        annotations = await self._fetch_all(
            request.task_id,
            "annotations",
            request.project_id,
            request.input_commit_id,
        )

        task_type = str(request.task_type or "").strip().lower()
        apply_label_filter = task_type in {"train", "eval"}
        include_label_ids = (
            self._extract_training_include_label_ids(request.resolved_params)
            if apply_label_filter
            else set()
        )
        original_label_count = len(labels)
        original_annotation_count = len(annotations)
        if include_label_ids:
            labels = [
                item
                for item in labels
                if str(item.get("id") or "").strip() in include_label_ids
            ]

        # `model` means unconfirmed assistant boxes and must never enter training.
        train_annotations = [
            item
            for item in annotations
            if str(item.get("source") or "").strip().lower() != "model"
        ]
        if include_label_ids:
            train_annotations = [
                item
                for item in train_annotations
                if str(item.get("category_id") or item.get("label_id") or "").strip() in include_label_ids
            ]
        if include_label_ids:
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "训练标签筛选完成 "
                        f"include_label_count={len(include_label_ids)} "
                        f"labels_kept={len(labels)} labels_filtered={max(0, original_label_count - len(labels))} "
                        f"annotations_kept={len(train_annotations)} "
                        f"annotations_filtered={max(0, original_annotation_count - len(train_annotations))}"
                    ),
                },
            )

        labeled_sample_ids = {
            str(item.get("sample_id") or "")
            for item in train_annotations
            if item.get("sample_id")
        }

        positive_samples = [
            dict(item)
            for item in samples
            if str(item.get("id") or "") in labeled_sample_ids
        ]
        negative_candidates = [
            dict(item)
            for item in samples
            if str(item.get("id") or "") not in labeled_sample_ids
        ]
        try:
            split_seed = max(0, int(runtime_context.split_seed))
        except Exception:
            split_seed = 0
        negative_sample_ratio = self._extract_training_negative_sample_ratio(request.resolved_params)
        negative_kept: list[dict[str, Any]] = list(negative_candidates)
        if task_type == "train":
            if negative_sample_ratio is None:
                negative_kept = list(negative_candidates)
            else:
                keep_limit = max(0, int(len(positive_samples) * max(0.0, float(negative_sample_ratio))))
                if keep_limit >= len(negative_candidates):
                    negative_kept = list(negative_candidates)
                elif keep_limit <= 0:
                    negative_kept = []
                else:
                    seeded = random.Random(split_seed)
                    shuffled = list(negative_candidates)
                    seeded.shuffle(shuffled)
                    negative_kept = shuffled[:keep_limit]
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "训练负样本采样完成 "
                        f"positive_samples={len(positive_samples)} "
                        f"negative_candidates={len(negative_candidates)} "
                        f"negative_kept={len(negative_kept)} "
                        f"negative_ratio={'inf' if negative_sample_ratio is None else f'{float(negative_sample_ratio):g}'}"
                    ),
                },
            )
        supervised_samples = (
            [*positive_samples, *negative_kept]
            if task_type == "train"
            else [*positive_samples, *negative_candidates]
        )
        if include_label_ids and not positive_samples:
            raise RuntimeError(
                "training label filter produced empty supervised dataset: "
                f"include_label_ids={sorted(include_label_ids)}"
            )
        plugin_cfg = plugin_params if isinstance(plugin_params, dict) else {}
        val_ratio_raw = plugin_cfg.get("val_split_ratio", 0.2)
        try:
            val_ratio = float(val_ratio_raw)
        except Exception:
            val_ratio = 0.2
        val_ratio = min(0.5, max(0.05, val_ratio))

        mode = str(runtime_context.mode or "").strip().lower()
        snapshot_mode = mode in {"active_learning", "simulation"} and task_type == "train"
        split_source = "random"
        if snapshot_mode:
            snapshot_split = self._split_samples_from_snapshot(samples=supervised_samples)
            if snapshot_split is None:
                raise RuntimeError(
                    "snapshot split hints are required for active_learning/simulation training data, "
                    "but received incomplete _snapshot_split metadata"
                )
            train_ids, val_ids, val_degraded = snapshot_split
            split_source = "snapshot"
        else:
            train_ids, val_ids, val_degraded = resolve_train_val_split(
                sample_ids=[str(item.get("id") or "") for item in supervised_samples if str(item.get("id") or "")],
                split_seed=split_seed,
                val_ratio=val_ratio,
            )
        splits: dict[str, list[dict[str, Any]]] = {
            "train": [],
            "val": [],
        }
        for item in supervised_samples:
            sample_id = str(item.get("id") or "")
            if not sample_id:
                continue
            split = "val" if sample_id in val_ids and not val_degraded else "train"
            item["_split"] = split
            item["_split_seed"] = split_seed
            item["_val_split_ratio"] = val_ratio
            item["_split_source"] = split_source
            splits[split].append(item)

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"训练数据划分完成 round_index={runtime_context.round_index} "
                    f"source={split_source} "
                    f"seed={split_seed} val_ratio={val_ratio:.3f} "
                    f"train={len(splits['train'])} val={len(splits['val'])} "
                    f"val_degraded={val_degraded}"
                ),
            },
        )

        protected: set[str] = set()
        for item in supervised_samples:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("step stop requested")
            asset_hash = item.get("asset_hash")
            download_url = item.get("download_url")
            if not asset_hash or not download_url:
                continue
            cached_path = await self._cache.ensure_cached(
                str(asset_hash),
                str(download_url),
                protected=protected,
                pin_task_id=request.task_id,
            )
            item["local_path"] = str(cached_path)
            protected.add(str(asset_hash))

        ir_batch, ir_report = build_training_batch_ir(
            labels=labels,
            samples=supervised_samples,
            annotations=train_annotations,
        )
        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "IR 训练批次构建完成 "
                    f"labels={ir_report.label_count} "
                    f"samples={ir_report.sample_count} "
                    f"annotations={ir_report.annotation_count} "
                    f"dropped_annotations={ir_report.dropped_annotation_count}"
                ),
            },
        )

        return TrainingDataBundle(
            labels=labels,
            samples=supervised_samples,
            train_annotations=train_annotations,
            ir_batch=ir_batch,
            ir_report=ir_report,
            protected=protected,
            splits=splits,
        )

    @staticmethod
    def _extract_training_include_label_ids(resolved_params: dict[str, Any] | None) -> set[str]:
        payload = resolved_params if isinstance(resolved_params, dict) else {}
        training = payload.get("training")
        training_cfg = training if isinstance(training, dict) else {}
        include_label_ids = training_cfg.get("include_label_ids")
        if not isinstance(include_label_ids, list):
            return set()
        normalized = {
            str(item or "").strip()
            for item in include_label_ids
            if str(item or "").strip()
        }
        return normalized

    @staticmethod
    def _extract_training_negative_sample_ratio(
        resolved_params: dict[str, Any] | None,
    ) -> float | None:
        payload = resolved_params if isinstance(resolved_params, dict) else {}
        training = payload.get("training")
        training_cfg = training if isinstance(training, dict) else {}
        if "negative_sample_ratio" not in training_cfg:
            return 0.0
        raw = training_cfg.get("negative_sample_ratio")
        if raw is None:
            return None
        try:
            value = float(raw)
        except Exception:
            return 0.0
        if not math.isfinite(value):
            return 0.0
        return max(0.0, value)

    @staticmethod
    def _split_samples_from_snapshot(
        *,
        samples: list[dict[str, Any]],
    ) -> tuple[set[str], set[str], bool] | None:
        train_ids: set[str] = set()
        val_ids: set[str] = set()
        hinted_count = 0
        total = 0
        for item in samples:
            sample_id = str(item.get("id") or "")
            if not sample_id:
                continue
            total += 1
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            split_hint = str(meta.get("_snapshot_split") or "").strip().lower()
            if split_hint not in {"train", "val"}:
                continue
            hinted_count += 1
            if split_hint == "val":
                val_ids.add(sample_id)
            else:
                train_ids.add(sample_id)
        if total == 0 or hinted_count == 0 or hinted_count != total:
            return None
        if not train_ids:
            return None
        return train_ids, val_ids, len(val_ids) == 0
