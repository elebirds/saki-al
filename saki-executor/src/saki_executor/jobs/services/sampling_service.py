from __future__ import annotations

import asyncio
import heapq
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.jobs.contracts import FetchedPage
from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import ExecutorPlugin

FetchPageFn = Callable[..., Awaitable[FetchedPage]]


class SamplingService:
    def __init__(
        self,
        *,
        fetch_page: FetchPageFn,
        cache: AssetCache,
        stop_event: asyncio.Event,
    ) -> None:
        self._fetch_page = fetch_page
        self._cache = cache
        self._stop_event = stop_event

    async def collect_topk_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: Workspace,
        task_id: str,
        project_id: str,
        commit_id: str,
        strategy: str,
        params: dict[str, Any],
        protected: set[str],
        topk: int,
    ) -> list[dict[str, Any]]:
        page_size = max(1, min(5000, int(params.get("unlabeled_page_size", 1000))))
        target_topk = max(1, topk)
        cursor: str | None = None
        heap: list[tuple[float, int, dict[str, Any]]] = []
        counter = 0

        while True:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("task stop requested")

            response = await self._fetch_page(
                task_id=task_id,
                query_type="unlabeled_samples",
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=page_size,
            )
            chunk = response.items
            if not chunk and not response.next_cursor:
                break

            for item in chunk:
                asset_hash = item.get("asset_hash")
                download_url = item.get("download_url")
                if not asset_hash or not download_url:
                    continue
                cached_path = await self._cache.ensure_cached(
                    str(asset_hash),
                    str(download_url),
                    protected=protected,
                    pin_job_id=task_id,
                )
                item["local_path"] = str(cached_path)
                protected.add(str(asset_hash))

            batch = await plugin.predict_unlabeled_batch(
                workspace=workspace,
                unlabeled_samples=chunk,
                strategy=strategy,
                params=params,
            )
            self._merge_batch_into_heap(
                heap=heap,
                batch=batch or [],
                target_topk=target_topk,
                counter_start=counter,
            )
            counter += len(batch or [])
            cursor = response.next_cursor
            if not cursor:
                break

        return self._build_ranked_output(heap)

    @staticmethod
    def _merge_batch_into_heap(
        *,
        heap: list[tuple[float, int, dict[str, Any]]],
        batch: list[dict[str, Any]],
        target_topk: int,
        counter_start: int,
    ) -> None:
        counter = counter_start
        for candidate in batch:
            sample_id = str(candidate.get("sample_id") or "")
            if not sample_id:
                continue
            try:
                score = float(candidate.get("score") or 0.0)
            except Exception:
                score = 0.0
            reason_payload = candidate.get("reason") or {}
            if not isinstance(reason_payload, dict):
                reason_payload = {}
            prediction_snapshot = candidate.get("prediction_snapshot")
            if isinstance(prediction_snapshot, dict) and prediction_snapshot:
                reason_payload = {**reason_payload, "prediction_snapshot": prediction_snapshot}
            payload = {
                "sample_id": sample_id,
                "score": score,
                "reason": reason_payload,
            }
            counter += 1
            key = (score, counter, payload)
            if len(heap) < target_topk:
                heapq.heappush(heap, key)
                continue
            smallest = heap[0]
            if score > smallest[0]:
                heapq.heapreplace(heap, key)

    @staticmethod
    def _build_ranked_output(heap: list[tuple[float, int, dict[str, Any]]]) -> list[dict[str, Any]]:
        ranked = sorted(heap, key=lambda item: item[0], reverse=True)
        output: list[dict[str, Any]] = []
        for rank, item in enumerate(ranked, start=1):
            payload = item[2]
            reason = payload.get("reason")
            if isinstance(reason, dict):
                payload["reason"] = {**reason, "rank": rank}
            output.append(payload)
        return output
