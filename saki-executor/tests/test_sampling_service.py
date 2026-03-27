from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.cache.asset_cache import CacheBatchResult
from saki_executor.steps.contracts import FetchedPage
from saki_executor.steps.services.sampling_service import SamplingService


class _CacheStub:
    def __init__(self, *, cached_hashes: set[str], root: Path) -> None:
        self._cached_hashes = set(cached_hashes)
        self._root = root

    def is_cached(self, asset_hash: str) -> bool:
        return asset_hash in self._cached_hashes

    async def ensure_cached_batch(
        self,
        items: list[tuple[str, str]],
        *,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback=None,
        yield_every: int = 64,
    ) -> CacheBatchResult:
        del protected, pin_task_id, progress_callback, yield_every
        paths: dict[str, Path] = {}
        cache_hits = 0
        cache_misses = 0
        for asset_hash, download_url in items:
            was_cached = asset_hash in self._cached_hashes
            path = await self.ensure_cached(asset_hash, download_url)
            paths[asset_hash] = path
            if was_cached:
                cache_hits += 1
            else:
                cache_misses += 1
        return CacheBatchResult(
            paths=paths,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            lookup_sec=0.0,
            flush_sec=0.0,
            dirty_entries=len(paths),
            flush_count=1 if paths else 0,
        )

    async def ensure_cached(
        self,
        asset_hash: str,
        download_url: str,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
    ) -> Path:
        del download_url, protected, pin_task_id
        path = self._root / asset_hash
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        self._cached_hashes.add(asset_hash)
        return path


class _PluginStub:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def predict_samples_batch(
        self,
        *,
        workspace,
        samples: list[dict[str, Any]],
        params: dict[str, Any],
        context,
    ) -> list[dict[str, Any]]:
        del workspace, params, context
        self.calls.append([str(item.get("id") or "") for item in samples])
        rows: list[dict[str, Any]] = []
        for item in samples:
            sample_id = str(item.get("id") or "")
            if sample_id == "sample-empty":
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": 0.0,
                        "reason": {"pred_count": 0},
                        "prediction_snapshot": {"base_predictions": []},
                    }
                )
                continue
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": 0.9,
                    "reason": {"pred_count": 1},
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "class_name": "target",
                                "confidence": 0.9,
                                "geometry": {"rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
                            }
                        ]
                    },
                }
            )
        return rows


class _TopkPluginStub:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def predict_unlabeled_batch(
        self,
        *,
        workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context,
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params, context
        self.calls.append([str(item.get("id") or "") for item in unlabeled_samples])
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(unlabeled_samples, start=1):
            sample_id = str(item.get("id") or "")
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": float(index),
                    "reason": {"rank_hint": index},
                }
            )
        return rows


class _BatchOnlyCacheStub:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def ensure_cached_batch(
        self,
        items: list[tuple[str, str]],
        *,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback=None,
        yield_every: int = 64,
    ) -> CacheBatchResult:
        del protected, pin_task_id, progress_callback, yield_every
        paths: dict[str, Path] = {}
        for asset_hash, _download_url in items:
            path = self._root / asset_hash
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            paths[asset_hash] = path
        return CacheBatchResult(
            paths=paths,
            cache_hits=len(items),
            cache_misses=0,
            lookup_sec=0.0,
            flush_sec=0.0,
            dirty_entries=len(items),
            flush_count=1 if items else 0,
        )


@pytest.mark.anyio
async def test_collect_prediction_candidates_streaming_emits_perf_logs(tmp_path: Path) -> None:
    pages = [
        FetchedPage(
            request_id="r1",
            reply_to="reply",
            task_id="task-1",
            query_type="samples",
            items=[
                {"id": "sample-a", "asset_hash": "hash-a", "download_url": "https://example/a"},
                {"id": "sample-empty", "asset_hash": "hash-b", "download_url": "https://example/b"},
            ],
            next_cursor="cursor-2",
        ),
        FetchedPage(
            request_id="r2",
            reply_to="reply",
            task_id="task-1",
            query_type="samples",
            items=[
                {"id": "sample-c", "asset_hash": "hash-c", "download_url": "https://example/c"},
            ],
            next_cursor=None,
        ),
    ]

    async def _fetch_page(**kwargs) -> FetchedPage:
        del kwargs
        if not pages:
            return FetchedPage(
                request_id="r3",
                reply_to="reply",
                task_id="task-1",
                query_type="samples",
                items=[],
                next_cursor=None,
            )
        return pages.pop(0)

    emitted_logs: list[dict[str, Any]] = []

    async def _emit_log(payload: dict[str, Any]) -> None:
        emitted_logs.append(dict(payload))

    service = SamplingService(
        fetch_page=_fetch_page,
        cache=_CacheStub(cached_hashes={"hash-a"}, root=tmp_path / "cache"),
        stop_event=asyncio.Event(),
    )
    plugin = _PluginStub()

    rows = await service.collect_prediction_candidates_streaming(
        plugin=plugin,
        workspace=object(),
        task_id="task-1",
        project_id="project-1",
        commit_id="commit-1",
        params={"predict_page_size": 2, "predict_conf": 0.1, "imgsz": 640, "batch": 16},
        protected=set(),
        query_type="samples",
        context=object(),
        emit_log=_emit_log,
    )

    assert [row["sample_id"] for row in rows] == ["sample-a", "sample-c", "sample-empty"]
    assert plugin.calls == [["sample-a", "sample-empty"], ["sample-c"]]

    phases = [str((payload.get("meta") or {}).get("phase") or "") for payload in emitted_logs]
    assert phases == ["start", "page", "page", "done"]

    first_page_meta = emitted_logs[1]["meta"]
    assert first_page_meta["samples"] == 2
    assert first_page_meta["cache_hits"] == 1
    assert first_page_meta["cache_misses"] == 1
    assert "cache_lookup_sec" in first_page_meta
    assert "cache_flush_sec" in first_page_meta
    assert first_page_meta["returned_rows"] == 2
    assert first_page_meta["nonempty_rows"] == 1
    assert first_page_meta["pred_boxes"] == 1

    done_meta = emitted_logs[-1]["meta"]
    assert done_meta["pages"] == 2
    assert done_meta["samples"] == 3
    assert done_meta["returned_rows"] == 3
    assert done_meta["nonempty_rows"] == 2
    assert done_meta["pred_boxes"] == 2


@pytest.mark.anyio
async def test_collect_prediction_candidates_streaming_yields_control_on_large_page(tmp_path: Path, monkeypatch) -> None:
    original_sleep = asyncio.sleep
    yield_calls: list[int] = []

    async def _tracked_sleep(delay: float) -> None:
        if delay == 0:
            yield_calls.append(1)
        await original_sleep(delay)

    monkeypatch.setattr("saki_executor.steps.services.sampling_service.asyncio.sleep", _tracked_sleep)

    page = FetchedPage(
        request_id="r1",
        reply_to="reply",
        task_id="task-1",
        query_type="samples",
        items=[
            {
                "id": f"sample-{idx}",
                "asset_hash": f"hash-{idx}",
                "download_url": f"https://example/{idx}",
            }
            for idx in range(260)
        ],
        next_cursor=None,
    )

    async def _fetch_page(**kwargs) -> FetchedPage:
        del kwargs
        return page

    service = SamplingService(
        fetch_page=_fetch_page,
        cache=_BatchOnlyCacheStub(root=tmp_path / "cache"),
        stop_event=asyncio.Event(),
    )
    plugin = _PluginStub()

    rows = await service.collect_prediction_candidates_streaming(
        plugin=plugin,
        workspace=object(),
        task_id="task-1",
        project_id="project-1",
        commit_id="commit-1",
        params={"predict_page_size": 260, "predict_conf": 0.1, "imgsz": 640, "batch": 16},
        protected=set(),
        query_type="samples",
        context=object(),
        emit_log=None,
    )

    assert len(rows) == 260
    assert len(yield_calls) >= 4


@pytest.mark.anyio
async def test_collect_topk_candidates_streaming_emits_perf_logs(tmp_path: Path) -> None:
    pages = [
        FetchedPage(
            request_id="r1",
            reply_to="reply",
            task_id="task-score",
            query_type="unlabeled_samples",
            items=[
                {"id": "sample-a", "asset_hash": "hash-a", "download_url": "https://example/a"},
                {"id": "sample-b", "asset_hash": "hash-b", "download_url": "https://example/b"},
            ],
            next_cursor="cursor-2",
        ),
        FetchedPage(
            request_id="r2",
            reply_to="reply",
            task_id="task-score",
            query_type="unlabeled_samples",
            items=[
                {"id": "sample-c", "asset_hash": "hash-c", "download_url": "https://example/c"},
            ],
            next_cursor=None,
        ),
    ]

    async def _fetch_page(**kwargs) -> FetchedPage:
        del kwargs
        if not pages:
            return FetchedPage(
                request_id="r3",
                reply_to="reply",
                task_id="task-score",
                query_type="unlabeled_samples",
                items=[],
                next_cursor=None,
            )
        return pages.pop(0)

    emitted_logs: list[dict[str, Any]] = []

    async def _emit_log(payload: dict[str, Any]) -> None:
        emitted_logs.append(dict(payload))

    service = SamplingService(
        fetch_page=_fetch_page,
        cache=_CacheStub(cached_hashes={"hash-a"}, root=tmp_path / "cache"),
        stop_event=asyncio.Event(),
    )
    plugin = _TopkPluginStub()

    rows = await service.collect_topk_candidates_streaming(
        plugin=plugin,
        workspace=object(),
        task_id="task-score",
        project_id="project-1",
        commit_id="commit-1",
        strategy="aug_iou_disagreement",
        params={"unlabeled_page_size": 2, "sampling_topk": 2, "imgsz": 640, "batch": 8},
        protected=set(),
        query_type="unlabeled_samples",
        topk=2,
        context=object(),
        emit_log=_emit_log,
    )

    assert [row["sample_id"] for row in rows] == ["sample-b", "sample-a"]
    assert plugin.calls == [["sample-a", "sample-b"], ["sample-c"]]

    phases = [str((payload.get("meta") or {}).get("phase") or "") for payload in emitted_logs]
    assert phases == ["start", "page", "page", "done"]

    start_meta = emitted_logs[0]["meta"]
    assert start_meta["strategy"] == "aug_iou_disagreement"
    assert start_meta["page_size"] == 2
    assert start_meta["target_topk"] == 2

    first_page_meta = emitted_logs[1]["meta"]
    assert first_page_meta["samples"] == 2
    assert first_page_meta["cache_hits"] == 1
    assert first_page_meta["cache_misses"] == 1
    assert "cache_lookup_sec" in first_page_meta
    assert "cache_flush_sec" in first_page_meta
    assert "infer_sec" in first_page_meta
    assert first_page_meta["returned_rows"] == 2

    done_meta = emitted_logs[-1]["meta"]
    assert done_meta["pages"] == 2
    assert done_meta["samples"] == 3
    assert done_meta["returned_rows"] == 3
