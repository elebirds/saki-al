from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.jobs.contracts import JobExecutionRequest
from saki_executor.plugins.base import ExecutorPlugin

FetchAllFn = Callable[[str, str, str, str], Awaitable[list[dict[str, Any]]]]
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]
NormalizeScheduleFn = Callable[[Any], list[float]]
ResolveRatioFn = Callable[[int, list[float]], float]


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
        normalize_simulation_ratio_schedule: NormalizeScheduleFn,
        resolve_simulation_ratio: ResolveRatioFn,
    ) -> None:
        self._fetch_all = fetch_all
        self._cache = cache
        self._stop_event = stop_event
        self._normalize_schedule = normalize_simulation_ratio_schedule
        self._resolve_ratio = resolve_simulation_ratio

    async def prepare(
        self,
        *,
        request: JobExecutionRequest,
        plugin: ExecutorPlugin,
        emit: EmitFn,
    ) -> TrainingDataBundle:
        labels = await self._fetch_all(
            request.job_id,
            "labels",
            request.project_id,
            request.source_commit_id,
        )
        samples = await self._fetch_all(
            request.job_id,
            "samples",
            request.project_id,
            request.source_commit_id,
        )
        annotations = await self._fetch_all(
            request.job_id,
            "annotations",
            request.project_id,
            request.source_commit_id,
        )

        train_samples = samples
        train_annotations = annotations
        if request.mode == "active_learning":
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

        if request.mode == "simulation":
            schedule = self._normalize_schedule(request.params.get("simulation_ratio_schedule"))
            ratio = self._resolve_ratio(request.iteration, schedule)
            train_samples, train_annotations = await plugin.select_simulation_subset(
                samples=samples,
                annotations=annotations,
                ratio=ratio,
                iteration=request.iteration,
                params=request.params,
            )
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"simulation mode enabled iteration={request.iteration} ratio={ratio:.4f} "
                        f"train_samples={len(train_samples)} train_annotations={len(train_annotations)}"
                    ),
                },
            )

        protected: set[str] = set()
        for item in train_samples:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")
            asset_hash = item.get("asset_hash")
            download_url = item.get("download_url")
            if not asset_hash or not download_url:
                continue
            cached_path = await self._cache.ensure_cached(
                str(asset_hash),
                str(download_url),
                protected=protected,
                pin_job_id=request.job_id,
            )
            item["local_path"] = str(cached_path)
            protected.add(str(asset_hash))

        return TrainingDataBundle(
            labels=labels,
            train_samples=train_samples,
            train_annotations=train_annotations,
            protected=protected,
        )

