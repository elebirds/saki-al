from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from saki_executor.cache.asset_cache import AssetCache


class _FakeStreamResponse:
    def __init__(self, payload: bytes, *, delay_sec: float = 0.0) -> None:
        self._payload = payload
        self._delay_sec = delay_sec
        self.status_code = 200
        self.headers = {"content-length": str(len(payload))}

    async def __aenter__(self) -> _FakeStreamResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def raise_for_status(self) -> None:
        return

    async def aiter_bytes(self, *, chunk_size: int):
        for index in range(0, len(self._payload), chunk_size):
            if self._delay_sec > 0:
                await asyncio.sleep(self._delay_sec)
            yield self._payload[index:index + chunk_size]


class _FakeAsyncClient:
    init_count = 0
    stream_calls: list[str] = []
    payloads: dict[str, bytes] = {}
    delay_sec = 0.0

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        type(self).init_count += 1

    async def aclose(self) -> None:
        return

    def stream(self, method: str, url: str) -> _FakeStreamResponse:
        assert method == "GET"
        type(self).stream_calls.append(url)
        return _FakeStreamResponse(type(self).payloads[url], delay_sec=type(self).delay_sec)


@pytest.mark.anyio
async def test_asset_cache_reuses_client_and_deduplicates_inflight_downloads(tmp_path: Path, monkeypatch) -> None:
    payload_a = b"hello-world-a"
    payload_b = b"hello-world-b"
    hash_a = hashlib.sha256(payload_a).hexdigest()
    hash_b = hashlib.sha256(payload_b).hexdigest()
    _FakeAsyncClient.init_count = 0
    _FakeAsyncClient.stream_calls = []
    _FakeAsyncClient.payloads = {
        "https://example.test/a": payload_a,
        "https://example.test/b": payload_b,
    }
    _FakeAsyncClient.delay_sec = 0.0
    monkeypatch.setattr("saki_executor.cache.asset_cache.httpx.AsyncClient", _FakeAsyncClient)

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024, download_concurrency=4)
    try:
        first, second = await asyncio.gather(
            cache.ensure_cached(hash_a, "https://example.test/a"),
            cache.ensure_cached(hash_a, "https://example.test/a"),
        )
        third = await cache.ensure_cached(hash_b, "https://example.test/b")
    finally:
        await cache.aclose()

    assert first == second
    assert first.read_bytes() == payload_a
    assert third.read_bytes() == payload_b
    assert _FakeAsyncClient.stream_calls.count("https://example.test/a") == 1
    assert _FakeAsyncClient.stream_calls.count("https://example.test/b") == 1
    assert _FakeAsyncClient.init_count == 1


@pytest.mark.anyio
async def test_asset_cache_cleans_up_tmp_file_when_download_cancelled(tmp_path: Path, monkeypatch) -> None:
    payload = (b"x" * 1024) * 8
    asset_hash = hashlib.sha256(payload).hexdigest()
    _FakeAsyncClient.init_count = 0
    _FakeAsyncClient.stream_calls = []
    _FakeAsyncClient.payloads = {"https://example.test/slow": payload}
    _FakeAsyncClient.delay_sec = 0.2
    monkeypatch.setattr("saki_executor.cache.asset_cache.httpx.AsyncClient", _FakeAsyncClient)

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024, download_concurrency=1)
    task = asyncio.create_task(cache.ensure_cached(asset_hash, "https://example.test/slow"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await cache.aclose()

    tmp_files = list((tmp_path / "cache").rglob("*.tmp-*"))
    assert tmp_files == []
    assert cache._inflight == {}  # noqa: SLF001


@pytest.mark.anyio
async def test_asset_cache_batch_all_hits_flushes_index_once(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    cache = AssetCache(root_dir=str(cache_dir), max_bytes=1024 * 1024, download_concurrency=2)
    write_calls: list[int] = []

    def _write_snapshot(path: Path, snapshot: dict[str, object]) -> None:
        write_calls.append(len(snapshot))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cache, "_write_index_snapshot", _write_snapshot)

    items: list[tuple[str, str]] = []
    for idx in range(1000):
        payload = f"cached-{idx}".encode("utf-8")
        asset_hash = hashlib.sha256(payload).hexdigest()
        path = cache._asset_path(asset_hash)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        items.append((asset_hash, f"https://example.test/{idx}"))

    result = await cache.ensure_cached_batch(items, protected=set(), pin_task_id="task-cache-hit")

    assert result.cache_hits == 1000
    assert result.cache_misses == 0
    assert result.flush_count == 1
    assert len(write_calls) == 1


@pytest.mark.anyio
async def test_asset_cache_batch_yields_control_for_large_hit_set(tmp_path: Path, monkeypatch) -> None:
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024, download_concurrency=2)
    yield_calls: list[int] = []
    original_sleep = asyncio.sleep

    async def _tracked_sleep(delay: float):
        if delay == 0:
            yield_calls.append(1)
        return await original_sleep(delay)

    monkeypatch.setattr("saki_executor.cache.asset_cache.asyncio.sleep", _tracked_sleep)

    items: list[tuple[str, str]] = []
    for idx in range(130):
        payload = f"yield-{idx}".encode("utf-8")
        asset_hash = hashlib.sha256(payload).hexdigest()
        path = cache._asset_path(asset_hash)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        items.append((asset_hash, f"https://example.test/yield-{idx}"))

    await cache.ensure_cached_batch(items, protected=set(), pin_task_id="task-yield")

    assert len(yield_calls) >= 2


@pytest.mark.anyio
async def test_asset_cache_aclose_flushes_dirty_index(tmp_path: Path, monkeypatch) -> None:
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024, download_concurrency=2)
    write_calls: list[int] = []

    def _write_snapshot(path: Path, snapshot: dict[str, object]) -> None:
        write_calls.append(len(snapshot))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cache, "_write_index_snapshot", _write_snapshot)

    async with cache._state_lock:  # noqa: SLF001
        cache._touch_index_record_locked(  # noqa: SLF001
            asset_hash="hash-dirty",
            size=12,
            last_access=1.0,
            pin_task_id="task-dirty",
        )

    await cache.aclose()

    assert len(write_calls) == 1
