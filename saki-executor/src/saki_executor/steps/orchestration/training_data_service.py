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
        mode = str(runtime_context.mode or "").strip().lower()
        manual_train_mode = mode == "manual" and task_type == "train"
        manual_negative_pool_scope = "empty_confirmed_only" if manual_train_mode else "n/a"
        empty_confirmed_candidates = 0
        unknown_review_state_count = 0
        if manual_train_mode:
            manual_negative_candidates: list[dict[str, Any]] = []
            for item in negative_candidates:
                review_state = self._extract_sample_commit_review_state(item)
                if review_state == "empty_confirmed":
                    manual_negative_candidates.append(item)
                elif review_state == "labeled":
                    continue
                else:
                    unknown_review_state_count += 1
            negative_candidates = manual_negative_candidates
            empty_confirmed_candidates = len(negative_candidates)
        try:
            split_seed = max(0, int(runtime_context.split_seed))
        except Exception:
            split_seed = 0
        training_cfg = (
            request.resolved_params.get("training")
            if isinstance(request.resolved_params, dict)
            else {}
        )
        training_cfg = training_cfg if isinstance(training_cfg, dict) else {}
        has_negative_ratio_config = "negative_sample_ratio" in training_cfg
        negative_ratio_raw = training_cfg.get("negative_sample_ratio")
        raw_ratio_text = (
            "未配置"
            if not has_negative_ratio_config
            else ("null" if negative_ratio_raw is None else str(negative_ratio_raw))
        )
        ratio_source_text = "显式配置" if has_negative_ratio_config else "默认值"
        negative_sample_ratio = self._extract_training_negative_sample_ratio(request.resolved_params)
        effective_ratio_text = (
            "inf"
            if negative_sample_ratio is None
            else f"{max(0.0, float(negative_sample_ratio)):g}"
        )
        negative_kept: list[dict[str, Any]] = list(negative_candidates)
        if task_type == "train":
            ratio_value = None if negative_sample_ratio is None else max(0.0, float(negative_sample_ratio))
            negative_adjust_enabled = negative_sample_ratio is None or (ratio_value is not None and ratio_value > 0.0)
            strategy_text = (
                "无限保留"
                if negative_sample_ratio is None
                else ("按比例采样" if ratio_value is not None and ratio_value > 0.0 else "关闭")
            )
            keep_limit = (
                len(negative_candidates)
                if negative_sample_ratio is None
                else max(0, int(len(positive_samples) * (ratio_value or 0.0)))
            )
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "插件启动-训练负采样策略检查 "
                        f"启动={'是' if negative_adjust_enabled else '否'} "
                        f"策略={strategy_text} "
                        f"配置来源={ratio_source_text} "
                        f"negative_sample_ratio原值={raw_ratio_text} "
                        f"negative_sample_ratio生效值={effective_ratio_text} "
                        f"正样本数={len(positive_samples)} "
                        f"负样本候选数={len(negative_candidates)} "
                        f"manual_negative_pool_scope={manual_negative_pool_scope} "
                        f"empty_confirmed_candidates={empty_confirmed_candidates} "
                        f"unknown_review_state_count={unknown_review_state_count} "
                        f"预计保留上限={keep_limit}"
                    ),
                },
            )
            if negative_sample_ratio is None:
                negative_kept = list(negative_candidates)
            else:
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
                        f"启动={'是' if negative_adjust_enabled else '否'} "
                        f"策略={strategy_text} "
                        f"配置来源={ratio_source_text} "
                        f"正样本数={len(positive_samples)} "
                        f"负样本候选数={len(negative_candidates)} "
                        f"负样本保留数={len(negative_kept)} "
                        f"负样本裁剪数={max(0, len(negative_candidates) - len(negative_kept))} "
                        f"manual_negative_pool_scope={manual_negative_pool_scope} "
                        f"empty_confirmed_candidates={empty_confirmed_candidates} "
                        f"unknown_review_state_count={unknown_review_state_count} "
                        f"保留上限={keep_limit} "
                        f"negative_ratio={'inf' if negative_sample_ratio is None else f'{float(negative_sample_ratio):g}'}"
                    ),
                },
            )
        else:
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "插件启动-训练负采样策略检查 "
                        "启动=否 "
                        "策略=关闭 "
                        "配置来源=非TRAIN阶段 "
                        f"task_type={task_type or 'unknown'} "
                        f"negative_sample_ratio原值={raw_ratio_text} "
                        f"negative_sample_ratio生效值={effective_ratio_text}"
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
    def _extract_sample_commit_review_state(sample: dict[str, Any] | None) -> str:
        if not isinstance(sample, dict):
            return ""
        meta = sample.get("meta")
        meta_map = meta if isinstance(meta, dict) else {}
        return str(meta_map.get("_commit_review_state") or "").strip().lower()

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
