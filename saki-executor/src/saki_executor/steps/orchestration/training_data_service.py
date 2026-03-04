from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import StepExecutionRequest
from saki_executor.steps.services import IRDatasetBuildReport, build_training_batch_ir
from saki_plugin_sdk import StepRuntimeContext, resolve_train_val_split
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
        request: StepExecutionRequest,
        plugin_params: dict[str, Any],
        runtime_context: StepRuntimeContext,
        emit: EmitFn,
    ) -> TrainingDataBundle:
        labels = await self._fetch_all(
            request.step_id,
            "labels",
            request.project_id,
            request.input_commit_id,
        )
        samples = await self._fetch_all(
            request.step_id,
            "samples",
            request.project_id,
            request.input_commit_id,
        )
        annotations = await self._fetch_all(
            request.step_id,
            "annotations",
            request.project_id,
            request.input_commit_id,
        )

        # `model` means unconfirmed assistant boxes and must never enter training.
        train_annotations = [
            item
            for item in annotations
            if str(item.get("source") or "").strip().lower() != "model"
        ]
        labeled_sample_ids = {
            str(item.get("sample_id") or "")
            for item in train_annotations
            if item.get("sample_id")
        }
        supervised_samples = [
            dict(item)
            for item in samples
            if str(item.get("id") or "") in labeled_sample_ids
        ]
        try:
            split_seed = max(0, int(runtime_context.split_seed))
        except Exception:
            split_seed = 0
        plugin_cfg = plugin_params if isinstance(plugin_params, dict) else {}
        val_ratio_raw = plugin_cfg.get("val_split_ratio", 0.2)
        try:
            val_ratio = float(val_ratio_raw)
        except Exception:
            val_ratio = 0.2
        val_ratio = min(0.5, max(0.05, val_ratio))

        mode = str(runtime_context.mode or "").strip().lower()
        snapshot_mode = mode in {"active_learning", "simulation"}
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
                    f"training split resolved round_index={runtime_context.round_index} "
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
                pin_step_id=request.step_id,
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
                    "ir training batch prepared "
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
