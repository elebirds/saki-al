from __future__ import annotations

import asyncio
import heapq
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import FetchedPage
from saki_plugin_sdk import ExecutionBindingContext, ExecutorPlugin, WorkspaceProtocol

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
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        strategy: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        topk: int,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        page_size = max(1, min(5000, int(params.get("unlabeled_page_size", 1000))))
        target_topk = int(topk)
        keep_all = target_topk <= 0
        cursor: str | None = None
        heap: list[tuple[float, int, dict[str, Any]]] = []
        rows: list[dict[str, Any]] = []
        counter = 0

        while True:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("step stop requested")

            response = await self._fetch_page(
                task_id=task_id,
                query_type=query_type,
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
                    pin_task_id=task_id,
                )
                item["local_path"] = str(cached_path)
                protected.add(str(asset_hash))

            call_params = params
            if keep_all:
                # keep_all means "do not truncate by topk"; some plugins still slice by topk,
                # so force per-page topk to current page size to preserve full recall.
                page_topk = len(chunk)
                if page_topk > 0:
                    call_params = dict(params)
                    call_params["topk"] = page_topk
                    call_params["sampling_topk"] = page_topk

            batch = await plugin.predict_unlabeled_batch(
                workspace=workspace,
                unlabeled_samples=chunk,
                strategy=strategy,
                params=call_params,
                context=context,
            )
            if keep_all:
                rows.extend(self._normalize_batch(batch or []))
            else:
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

        if keep_all:
            return self._build_ranked_output_from_rows(rows)
        return self._build_ranked_output(heap)

    @staticmethod
    def _normalize_batch(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for idx, candidate in enumerate(batch):
            if not isinstance(candidate, dict):
                raise ValueError(f"candidate[{idx}] must be an object")
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
            prediction_snapshot_exists = "prediction_snapshot" in candidate
            prediction_snapshot = candidate.get("prediction_snapshot")
            if prediction_snapshot_exists and prediction_snapshot is not None and not isinstance(prediction_snapshot, dict):
                raise ValueError(f"candidate[{idx}].prediction_snapshot must be an object")
            if isinstance(prediction_snapshot, dict) and prediction_snapshot:
                reason_payload = {**reason_payload, "prediction_snapshot": prediction_snapshot}
            normalized.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason_payload,
                }
            )
        return normalized

    @staticmethod
    def _merge_batch_into_heap(
        *,
        heap: list[tuple[float, int, dict[str, Any]]],
        batch: list[dict[str, Any]],
        target_topk: int,
        counter_start: int,
    ) -> None:
        counter = counter_start
        for payload in SamplingService._normalize_batch(batch):
            score = float(payload.get("score") or 0.0)
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

    @staticmethod
    def _build_ranked_output_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(rows, key=lambda item: float(item.get("score") or 0.0), reverse=True)
        output: list[dict[str, Any]] = []
        for rank, payload in enumerate(ranked, start=1):
            row = dict(payload)
            reason = row.get("reason")
            if isinstance(reason, dict):
                row["reason"] = {**reason, "rank": rank}
            output.append(row)
        return output
