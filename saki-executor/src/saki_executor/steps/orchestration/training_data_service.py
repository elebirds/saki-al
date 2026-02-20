from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import StepExecutionRequest
from saki_executor.steps.services import IRDatasetBuildReport, build_training_batch_ir
from saki_executor.plugins.base import ExecutorPlugin
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb

FetchAllFn = Callable[[str, str, str, str], Awaitable[list[dict[str, Any]]]]
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class TrainingDataBundle:
    labels: list[dict[str, Any]]
    train_samples: list[dict[str, Any]]
    train_annotations: list[dict[str, Any]]
    ir_batch: irpb.DataBatchIR
    ir_report: IRDatasetBuildReport
    protected: set[str]


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
        plugin: ExecutorPlugin,
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

        train_samples = samples
        train_annotations = annotations
        if request.mode in {"active_learning", "simulation"}:
            labeled_sample_ids = {
                str(item.get("sample_id") or "")
                for item in annotations
                if item.get("sample_id")
            }
            if labeled_sample_ids:
                train_samples = [
                    item
                    for item in samples
                    if str(item.get("id") or "") in labeled_sample_ids
                ]
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"simulation mode enabled round_index={request.round_index} "
                        f"train_samples={len(train_samples)} train_annotations={len(train_annotations)}"
                    ),
                },
            )

        protected: set[str] = set()
        for item in train_samples:
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
            samples=train_samples,
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
            train_samples=train_samples,
            train_annotations=train_annotations,
            ir_batch=ir_batch,
            ir_report=ir_report,
            protected=protected,
        )
