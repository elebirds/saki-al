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
