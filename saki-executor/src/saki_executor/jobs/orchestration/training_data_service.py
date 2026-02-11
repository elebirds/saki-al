from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.jobs.contracts import TaskExecutionRequest
from saki_executor.plugins.base import ExecutorPlugin

FetchAllFn = Callable[[str, str, str, str], Awaitable[list[dict[str, Any]]]]
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class TrainingDataBundle:
    labels: list[dict[str, Any]]
    train_samples: list[dict[str, Any]]
    train_annotations: list[dict[str, Any]]
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
        request: TaskExecutionRequest,
        plugin: ExecutorPlugin,
        emit: EmitFn,
    ) -> TrainingDataBundle:
        labels = await self._fetch_all(
            request.task_id,
            "labels",
            request.project_id,
            request.source_commit_id,
        )
        samples = await self._fetch_all(
            request.task_id,
            "samples",
            request.project_id,
            request.source_commit_id,
        )
        annotations = await self._fetch_all(
            request.task_id,
            "annotations",
            request.project_id,
            request.source_commit_id,
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
                raise asyncio.CancelledError("task stop requested")
            asset_hash = item.get("asset_hash")
            download_url = item.get("download_url")
            if not asset_hash or not download_url:
                continue
            cached_path = await self._cache.ensure_cached(
                str(asset_hash),
                str(download_url),
                protected=protected,
                pin_job_id=request.task_id,
            )
            item["local_path"] = str(cached_path)
            protected.add(str(asset_hash))

        return TrainingDataBundle(
            labels=labels,
            train_samples=train_samples,
            train_annotations=train_annotations,
            protected=protected,
        )
