from __future__ import annotations

import asyncio
import heapq
import time
from typing import Any, Awaitable, Callable

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.core.config import settings
from saki_executor.steps.contracts import FetchedPage
from saki_plugin_sdk import ExecutionBindingContext, ExecutorPlugin, WorkspaceProtocol

FetchPageFn = Callable[..., Awaitable[FetchedPage]]
EmitLogFn = Callable[[dict[str, Any]], Awaitable[None]]


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

            await self._cache_page_assets(
                chunk=chunk,
                protected=protected,
                pin_task_id=task_id,
            )

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

    async def collect_prediction_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        context: ExecutionBindingContext,
        emit_log: EmitLogFn | None = None,
    ) -> list[dict[str, Any]]:
        page_size = max(1, min(5000, int(params.get("predict_page_size", params.get("unlabeled_page_size", 1000)))))
        cursor: str | None = None
        rows: list[dict[str, Any]] = []
        total_started_at = time.perf_counter()
        page_index = 0
        total_samples = 0
        total_batch_rows = 0
        total_nonempty_rows = 0
        total_pred_boxes = 0
        total_fetch_sec = 0.0
        total_cache_sec = 0.0
        total_predict_sec = 0.0
        total_normalize_sec = 0.0

        await self._emit_prediction_log(
            emit_log,
            level="INFO",
            message=(
                "Prediction 分页采集开始 "
                f"page_size={page_size} predict_conf={params.get('predict_conf')} "
                f"imgsz={params.get('imgsz')} batch={params.get('batch')}"
            ),
            meta={
                "phase": "start",
                "page_size": page_size,
                "predict_conf": params.get("predict_conf"),
                "imgsz": params.get("imgsz"),
                "batch": params.get("batch"),
                "query_type": query_type,
            },
        )

        while True:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("step stop requested")

            page_index += 1
            fetch_started_at = time.perf_counter()
            response = await self._fetch_page(
                task_id=task_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=page_size,
            )
            fetch_sec = time.perf_counter() - fetch_started_at
            total_fetch_sec += fetch_sec
            chunk = response.items
            if not chunk and not response.next_cursor:
                break

            cache_started_at = time.perf_counter()
            cache_result = await self._cache_page_assets(
                chunk=chunk,
                protected=protected,
                pin_task_id=task_id,
            )
            cache_sec = time.perf_counter() - cache_started_at
            total_cache_sec += cache_sec

            predict_started_at = time.perf_counter()
            batch = await plugin.predict_samples_batch(
                workspace=workspace,
                samples=chunk,
                params=params,
                context=context,
            )
            predict_sec = time.perf_counter() - predict_started_at
            total_predict_sec += predict_sec

            normalize_started_at = time.perf_counter()
            normalized_batch = self._normalize_batch(batch or [])
            normalize_sec = time.perf_counter() - normalize_started_at
            total_normalize_sec += normalize_sec
            rows.extend(normalized_batch)

            page_nonempty_rows, page_pred_boxes = self._summarize_prediction_batch(batch or [])
            total_samples += len(chunk)
            total_batch_rows += len(batch or [])
            total_nonempty_rows += page_nonempty_rows
            total_pred_boxes += page_pred_boxes

            await self._emit_prediction_log(
                emit_log,
                level="WARN" if cache_sec > float(settings.HEARTBEAT_INTERVAL_SEC) else "INFO",
                message=(
                    f"Prediction 分页[{page_index}] samples={len(chunk)} "
                    f"fetch={fetch_sec:.3f}s cache={cache_sec:.3f}s "
                    f"(lookup={cache_result.lookup_sec:.3f}s flush={cache_result.flush_sec:.3f}s "
                    f"hit={cache_result.cache_hits} miss={cache_result.cache_misses} "
                    f"mode={'all_hit' if cache_result.all_hit else 'mixed'} "
                    f"dirty={cache_result.dirty_entries} flushes={cache_result.flush_count}) "
                    f"predict={predict_sec:.3f}s normalize={normalize_sec:.3f}s "
                    f"returned={len(batch or [])} nonempty={page_nonempty_rows} boxes={page_pred_boxes}"
                ),
                meta={
                    "phase": "page",
                    "page_index": page_index,
                    "samples": len(chunk),
                    "fetch_sec": round(fetch_sec, 6),
                    "cache_sec": round(cache_sec, 6),
                    "cache_lookup_sec": round(cache_result.lookup_sec, 6),
                    "cache_flush_sec": round(cache_result.flush_sec, 6),
                    "cache_hits": cache_result.cache_hits,
                    "cache_misses": cache_result.cache_misses,
                    "cache_all_hit": bool(cache_result.all_hit),
                    "cache_dirty_entries": cache_result.dirty_entries,
                    "cache_flush_count": cache_result.flush_count,
                    "predict_sec": round(predict_sec, 6),
                    "normalize_sec": round(normalize_sec, 6),
                    "returned_rows": len(batch or []),
                    "normalized_rows": len(normalized_batch),
                    "nonempty_rows": page_nonempty_rows,
                    "pred_boxes": page_pred_boxes,
                    "cumulative_samples": total_samples,
                    "cumulative_returned_rows": total_batch_rows,
                    "cumulative_nonempty_rows": total_nonempty_rows,
                    "cumulative_pred_boxes": total_pred_boxes,
                },
            )
            cursor = response.next_cursor
            if not cursor:
                break

        rank_started_at = time.perf_counter()
        ranked_rows = self._build_ranked_output_from_rows(rows)
        rank_sec = time.perf_counter() - rank_started_at
        total_sec = time.perf_counter() - total_started_at
        await self._emit_prediction_log(
            emit_log,
            level="INFO",
            message=(
                f"Prediction 分页采集完成 pages={page_index} samples={total_samples} "
                f"fetch={total_fetch_sec:.3f}s cache={total_cache_sec:.3f}s "
                f"predict={total_predict_sec:.3f}s normalize={total_normalize_sec:.3f}s "
                f"rank={rank_sec:.3f}s total={total_sec:.3f}s "
                f"returned={total_batch_rows} nonempty={total_nonempty_rows} boxes={total_pred_boxes}"
            ),
            meta={
                "phase": "done",
                "pages": page_index,
                "samples": total_samples,
                "fetch_sec": round(total_fetch_sec, 6),
                "cache_sec": round(total_cache_sec, 6),
                "predict_sec": round(total_predict_sec, 6),
                "normalize_sec": round(total_normalize_sec, 6),
                "rank_sec": round(rank_sec, 6),
                "total_sec": round(total_sec, 6),
                "returned_rows": total_batch_rows,
                "nonempty_rows": total_nonempty_rows,
                "pred_boxes": total_pred_boxes,
            },
        )
        return ranked_rows

    async def _cache_page_assets(
        self,
        *,
        chunk: list[dict[str, Any]],
        protected: set[str],
        pin_task_id: str,
    ):
        jobs: list[tuple[str, str]] = []
        for index, item in enumerate(chunk, start=1):
            asset_hash = str(item.get("asset_hash") or "").strip()
            download_url = str(item.get("download_url") or "").strip()
            if not asset_hash or not download_url:
                continue
            jobs.append((asset_hash, download_url))
            protected.add(asset_hash)
            if index % 128 == 0:
                await asyncio.sleep(0)

        result = await self._cache.ensure_cached_batch(
            jobs,
            protected=protected,
            pin_task_id=pin_task_id,
        )
        for index, item in enumerate(chunk, start=1):
            asset_hash = str(item.get("asset_hash") or "").strip()
            if not asset_hash:
                continue
            cached_path = result.paths.get(asset_hash)
            if cached_path is not None:
                item["local_path"] = str(cached_path)
            if index % 128 == 0:
                await asyncio.sleep(0)
        return result

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

    @staticmethod
    async def _emit_prediction_log(
        emit_log: EmitLogFn | None,
        *,
        level: str,
        message: str,
        meta: dict[str, Any],
    ) -> None:
        if emit_log is None:
            return
        await emit_log(
            {
                "level": level,
                "message": message,
                "message_key": "prediction.perf",
                "message_args": dict(meta),
                "meta": dict(meta),
            }
        )

    @staticmethod
    def _summarize_prediction_batch(batch: list[dict[str, Any]]) -> tuple[int, int]:
        nonempty_rows = 0
        pred_boxes = 0
        for item in batch:
            if not isinstance(item, dict):
                continue
            snapshot_raw = item.get("prediction_snapshot")
            snapshot = snapshot_raw if isinstance(snapshot_raw, dict) else {}
            box_count = 0
            for key in ("base_predictions", "predictions"):
                rows_raw = snapshot.get(key)
                if isinstance(rows_raw, list):
                    box_count = len(rows_raw)
                    if box_count > 0:
                        break
            if box_count > 0:
                nonempty_rows += 1
                pred_boxes += box_count
        return nonempty_rows, pred_boxes
