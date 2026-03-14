from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.core.config import settings
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


@dataclass(frozen=True)
class TrainingDataPlan:
    labels: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    train_annotations: list[dict[str, Any]]
    splits: dict[str, list[dict[str, Any]]]
    split_seed: int
    val_ratio: float


class _AssetDownloadProgressTracker:
    def __init__(
        self,
        *,
        emit: EmitFn,
        total_samples: int,
        total_unique_assets: int,
        expected_cache_hits: int,
        concurrency: int,
    ) -> None:
        self._emit = emit
        self._total_samples = max(0, int(total_samples))
        self._total_unique_assets = max(0, int(total_unique_assets))
        self._expected_cache_hits = max(0, int(expected_cache_hits))
        self._concurrency = max(1, int(concurrency))
        self._progress_interval_sec = max(1, int(settings.ASSET_DOWNLOAD_PROGRESS_INTERVAL_SEC))
        self._progress_min_file_delta = max(1, int(settings.ASSET_DOWNLOAD_PROGRESS_MIN_FILE_DELTA))
        self._start_at = time.monotonic()
        self._last_emit_at = 0.0
        self._last_completed_logged = 0
        self._done = asyncio.Event()
        self._dirty = True
        self._completed_cache_hits = 0
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._downloaded_bytes = 0
        self._active_downloads = 0

    @property
    def total_remote_downloads(self) -> int:
        return max(0, self._total_unique_assets - self._expected_cache_hits)

    def handle_cache_event(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event") or "").strip().lower()
        if event == "cache_hit":
            self._completed_cache_hits += 1
        elif event == "download_started":
            self._active_downloads += 1
        elif event == "download_progress":
            self._downloaded_bytes += max(0, int(payload.get("bytes_delta") or 0))
        elif event == "download_completed":
            self._active_downloads = max(0, self._active_downloads - 1)
            self._completed_downloads += 1
        elif event == "download_failed":
            self._active_downloads = max(0, self._active_downloads - 1)
            self._failed_downloads += 1
        else:
            return
        self._dirty = True

    async def emit_start(self) -> None:
        await self._emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "训练资产下载开始 "
                    f"total_samples={self._total_samples} "
                    f"unique_assets={self._total_unique_assets} "
                    f"cache_hits={self._expected_cache_hits} "
                    f"remote_downloads={self.total_remote_downloads} "
                    f"concurrency={self._concurrency}"
                ),
                "message_key": "asset.download.progress",
                "meta": {
                    "phase": "start",
                    "total_samples": self._total_samples,
                    "unique_assets": self._total_unique_assets,
                    "cache_hits": self._expected_cache_hits,
                    "remote_downloads": self.total_remote_downloads,
                    "concurrency": self._concurrency,
                },
            },
        )

    async def run_periodic_reporter(self) -> None:
        try:
            while not self._done.is_set():
                await asyncio.wait_for(self._done.wait(), timeout=self._progress_interval_sec)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        while not self._done.is_set():
            await self._maybe_emit_progress()
            try:
                await asyncio.wait_for(self._done.wait(), timeout=self._progress_interval_sec)
            except asyncio.TimeoutError:
                continue
        await self._maybe_emit_progress(force=True)

    async def emit_success(self) -> None:
        elapsed = max(0.001, time.monotonic() - self._start_at)
        await self._emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "训练资产下载完成 "
                    f"total_samples={self._total_samples} "
                    f"unique_assets={self._total_unique_assets} "
                    f"cache_hits={self._completed_cache_hits}/{self._expected_cache_hits} "
                    f"downloaded={self._completed_downloads}/{self.total_remote_downloads} "
                    f"failed={self._failed_downloads} "
                    f"downloaded_bytes={self._downloaded_bytes} "
                    f"elapsed_sec={elapsed:.1f} "
                    f"avg_speed={self._format_rate(self._downloaded_bytes / elapsed)}"
                ),
                "message_key": "asset.download.progress",
                "meta": {
                    "phase": "complete",
                    "total_samples": self._total_samples,
                    "unique_assets": self._total_unique_assets,
                    "cache_hits_completed": self._completed_cache_hits,
                    "cache_hits_expected": self._expected_cache_hits,
                    "downloaded_completed": self._completed_downloads,
                    "downloaded_expected": self.total_remote_downloads,
                    "failed": self._failed_downloads,
                    "downloaded_bytes": self._downloaded_bytes,
                    "elapsed_sec": round(elapsed, 3),
                },
            },
        )

    async def emit_failure(self, error: BaseException) -> None:
        elapsed = max(0.001, time.monotonic() - self._start_at)
        await self._emit(
            "log",
            {
                "level": "ERROR",
                "message": (
                    "训练资产下载失败 "
                    f"total_samples={self._total_samples} "
                    f"unique_assets={self._total_unique_assets} "
                    f"cache_hits={self._completed_cache_hits}/{self._expected_cache_hits} "
                    f"downloaded={self._completed_downloads}/{self.total_remote_downloads} "
                    f"failed={self._failed_downloads} "
                    f"downloaded_bytes={self._downloaded_bytes} "
                    f"elapsed_sec={elapsed:.1f} "
                    f"error={error}"
                ),
                "message_key": "asset.download.progress",
                "meta": {
                    "phase": "fail",
                    "total_samples": self._total_samples,
                    "unique_assets": self._total_unique_assets,
                    "cache_hits_completed": self._completed_cache_hits,
                    "cache_hits_expected": self._expected_cache_hits,
                    "downloaded_completed": self._completed_downloads,
                    "downloaded_expected": self.total_remote_downloads,
                    "failed": self._failed_downloads,
                    "downloaded_bytes": self._downloaded_bytes,
                    "elapsed_sec": round(elapsed, 3),
                    "error": str(error),
                },
            },
        )

    def finish(self) -> None:
        self._done.set()

    async def _maybe_emit_progress(self, *, force: bool = False) -> None:
        if not force and not self._dirty:
            return
        now = time.monotonic()
        completed_files = self._completed_cache_hits + self._completed_downloads
        if not force:
            if completed_files - self._last_completed_logged < self._progress_min_file_delta and now - self._last_emit_at < self._progress_interval_sec:
                return
        elapsed = max(0.001, now - self._start_at)
        await self._emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "训练资产下载进度 "
                    f"completed={completed_files}/{self._total_unique_assets} "
                    f"cache_hits={self._completed_cache_hits}/{self._expected_cache_hits} "
                    f"downloaded={self._completed_downloads}/{self.total_remote_downloads} "
                    f"active={self._active_downloads} "
                    f"failed={self._failed_downloads} "
                    f"downloaded_bytes={self._downloaded_bytes} "
                    f"elapsed_sec={elapsed:.1f} "
                    f"speed={self._format_rate(self._downloaded_bytes / elapsed)}"
                ),
                "message_key": "asset.download.progress",
                "meta": {
                    "phase": "progress",
                    "completed": completed_files,
                    "total_unique_assets": self._total_unique_assets,
                    "cache_hits_completed": self._completed_cache_hits,
                    "cache_hits_expected": self._expected_cache_hits,
                    "downloaded_completed": self._completed_downloads,
                    "downloaded_expected": self.total_remote_downloads,
                    "active_downloads": self._active_downloads,
                    "failed": self._failed_downloads,
                    "downloaded_bytes": self._downloaded_bytes,
                    "elapsed_sec": round(elapsed, 3),
                },
            },
        )
        self._dirty = False
        self._last_emit_at = now
        self._last_completed_logged = completed_files

    @staticmethod
    def _format_rate(value: float) -> str:
        return f"{_format_bytes(int(max(0.0, value)))}/s"


def _format_bytes(value: int) -> str:
    size = float(max(0, int(value)))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{int(value)}B"


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
        plan = await self.plan(
            request=request,
            plugin_params=plugin_params,
            runtime_context=runtime_context,
            emit=emit,
        )
        return await self.materialize_plan(
            request=request,
            plan=plan,
            emit=emit,
        )

    async def plan(
        self,
        *,
        request: TaskExecutionRequest,
        plugin_params: dict[str, Any],
        runtime_context: TaskRuntimeContext,
        emit: EmitFn,
    ) -> TrainingDataPlan:
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

        return TrainingDataPlan(
            labels=labels,
            samples=supervised_samples,
            train_annotations=train_annotations,
            splits=splits,
            split_seed=split_seed,
            val_ratio=val_ratio,
        )

    async def materialize_plan(
        self,
        *,
        request: TaskExecutionRequest,
        plan: TrainingDataPlan,
        emit: EmitFn,
    ) -> TrainingDataBundle:
        labels = list(plan.labels)
        supervised_samples = [dict(item) for item in plan.samples]
        train_annotations = list(plan.train_annotations)
        splits = {
            "train": [dict(item) for item in (plan.splits.get("train") or [])],
            "val": [dict(item) for item in (plan.splits.get("val") or [])],
        }

        protected = await self._prefetch_supervised_assets(
            request=request,
            supervised_samples=supervised_samples,
            emit=emit,
        )

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

    def build_prepared_data_cache_fingerprint(
        self,
        *,
        request: TaskExecutionRequest,
        plugin_params: dict[str, Any],
        runtime_context: TaskRuntimeContext,
        plan: TrainingDataPlan,
    ) -> str:
        plugin_subset = {
            str(key): plugin_params.get(key)
            for key in sorted(plugin_params.keys())
            if not str(key).startswith("_") and str(key) not in {"task_type"}
        }
        payload = {
            "version": 1,
            "cache_kind": "prepared_data_v2",
            "plugin_id": str(request.plugin_id or "").strip(),
            "project_id": str(request.project_id or "").strip(),
            "input_commit_id": str(request.input_commit_id or "").strip(),
            "mode": str(runtime_context.mode or "").strip(),
            "split_seed": int(plan.split_seed),
            "val_ratio": float(plan.val_ratio),
            "plugin_subset": plugin_subset,
            "labels": self._canonicalize_labels(plan.labels),
            "samples": self._canonicalize_samples(plan.samples),
            "splits": {
                "train": sorted(
                    str(item.get("id") or "").strip()
                    for item in (plan.splits.get("train") or [])
                    if str(item.get("id") or "").strip()
                ),
                "val": sorted(
                    str(item.get("id") or "").strip()
                    for item in (plan.splits.get("val") or [])
                    if str(item.get("id") or "").strip()
                ),
            },
            "annotations": self._canonicalize_annotations(plan.train_annotations),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _prefetch_supervised_assets(
        self,
        *,
        request: TaskExecutionRequest,
        supervised_samples: list[dict[str, Any]],
        emit: EmitFn,
    ) -> set[str]:
        protected: set[str] = set()
        jobs: dict[str, str] = {}
        for item in supervised_samples:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("step stop requested")
            asset_hash = str(item.get("asset_hash") or "").strip()
            download_url = str(item.get("download_url") or "").strip()
            if not asset_hash or not download_url:
                continue
            jobs.setdefault(asset_hash, download_url)

        if not jobs:
            return protected

        protected.update(jobs.keys())
        expected_cache_hits = sum(1 for asset_hash in jobs if self._cache.is_cached(asset_hash))
        tracker = _AssetDownloadProgressTracker(
            emit=emit,
            total_samples=len(supervised_samples),
            total_unique_assets=len(jobs),
            expected_cache_hits=expected_cache_hits,
            concurrency=self._cache.download_concurrency,
        )
        await tracker.emit_start()
        reporter_task = asyncio.create_task(
            tracker.run_periodic_reporter(),
            name=f"asset-progress:{request.task_id}",
        )
        cache_task = asyncio.create_task(
            self._cache.ensure_cached_batch(
                list(jobs.items()),
                protected=protected,
                pin_task_id=request.task_id,
                progress_callback=tracker.handle_cache_event,
            ),
            name=f"asset-cache-batch:{request.task_id}",
        )
        stop_task = asyncio.create_task(
            self._stop_event.wait(),
            name=f"asset-stop:{request.task_id}",
        )
        try:
            done, _ = await asyncio.wait(
                {stop_task, cache_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done and self._stop_event.is_set():
                cache_task.cancel()
                await asyncio.gather(cache_task, return_exceptions=True)
                raise asyncio.CancelledError("step stop requested")
            cache_result = await cache_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await tracker.emit_failure(exc)
            raise
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            tracker.finish()
            try:
                await reporter_task
            except asyncio.CancelledError:
                pass

        resolved_by_hash = dict(cache_result.paths)
        for item in supervised_samples:
            asset_hash = str(item.get("asset_hash") or "").strip()
            if not asset_hash:
                continue
            cached_path = resolved_by_hash.get(asset_hash)
            if cached_path is not None:
                item["local_path"] = str(cached_path)

        await tracker.emit_success()
        return protected

    @staticmethod
    def _canonicalize_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [
            {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "color": str(item.get("color") or "").strip(),
            }
            for item in labels
            if str(item.get("id") or "").strip()
        ]
        return sorted(rows, key=lambda item: item["id"])

    @staticmethod
    def _canonicalize_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in samples:
            sample_id = str(item.get("id") or "").strip()
            if not sample_id:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            try:
                width = int(item.get("width") or 0)
            except Exception:
                width = 0
            try:
                height = int(item.get("height") or 0)
            except Exception:
                height = 0
            rows.append(
                {
                    "id": sample_id,
                    "asset_hash": str(item.get("asset_hash") or "").strip(),
                    "width": width,
                    "height": height,
                    "split": str(item.get("_split") or "").strip().lower(),
                    "split_source": str(item.get("_split_source") or "").strip().lower(),
                    "snapshot_partition": str(meta.get("_snapshot_partition") or "").strip().lower(),
                }
            )
        return sorted(rows, key=lambda item: item["id"])

    @staticmethod
    def _canonicalize_annotations(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in annotations:
            sample_id = str(item.get("sample_id") or "").strip()
            label_id = str(item.get("category_id") or item.get("label_id") or "").strip()
            if not sample_id or not label_id:
                continue
            obb = item.get("obb") if isinstance(item.get("obb"), dict) else None
            bbox_xywh = item.get("bbox_xywh")
            rows.append(
                {
                    "id": str(item.get("id") or "").strip(),
                    "sample_id": sample_id,
                    "label_id": label_id,
                    "source": str(item.get("source") or "").strip().lower(),
                    "confidence": item.get("confidence"),
                    "bbox_xywh": list(bbox_xywh) if isinstance(bbox_xywh, (list, tuple)) else None,
                    "obb": {
                        "cx": obb.get("cx"),
                        "cy": obb.get("cy"),
                        "width": obb.get("width", obb.get("w")),
                        "height": obb.get("height", obb.get("h")),
                        "angle": obb.get("angle_deg_ccw", obb.get("angle_deg", obb.get("angle"))),
                        "normalized": obb.get("normalized"),
                    }
                    if obb
                    else None,
                }
            )
        return sorted(rows, key=lambda item: (item["sample_id"], item["label_id"], item["id"]))

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
