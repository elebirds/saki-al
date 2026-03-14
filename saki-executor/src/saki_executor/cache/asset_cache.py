import asyncio
import hashlib
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

AssetProgressFn = Callable[[dict[str, Any]], None]
ActivityFn = Callable[[str], None]

_CACHE_BATCH_YIELD_EVERY = 64


@dataclass(frozen=True)
class CacheBatchResult:
    paths: dict[str, Path]
    cache_hits: int
    cache_misses: int
    lookup_sec: float
    flush_sec: float
    dirty_entries: int
    flush_count: int

    @property
    def all_hit(self) -> bool:
        return self.cache_misses == 0


class AssetCache:
    def __init__(
        self,
        root_dir: str,
        max_bytes: int,
        *,
        download_concurrency: int = 8,
        http_timeout_sec: int = 120,
        activity_callback: ActivityFn | None = None,
    ):
        self.root = Path(root_dir)
        self.max_bytes = max_bytes
        self.assets_dir = self.root / "assets"
        self.index_path = self.root / "cache_index.json"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()
        self._download_concurrency = max(1, int(download_concurrency or 1))
        self._http_timeout_sec = max(30, int(http_timeout_sec or 120))
        self._activity_callback = activity_callback
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._download_semaphore = asyncio.Semaphore(self._download_concurrency)
        self._inflight: dict[str, asyncio.Task[Path]] = {}
        self._inflight_lock = asyncio.Lock()
        self._index_version = 0
        self._flushed_index_version = 0
        self._index_version = 1 if self._index else 0
        self._flushed_index_version = self._index_version

    @property
    def download_concurrency(self) -> int:
        return self._download_concurrency

    def set_activity_callback(self, callback: ActivityFn | None) -> None:
        self._activity_callback = callback

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _build_index_snapshot(index: dict[str, Any]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for asset_hash, data in index.items():
            if isinstance(data, dict):
                snapshot[asset_hash] = dict(data)
            else:
                snapshot[asset_hash] = data
        return snapshot

    @staticmethod
    def _write_index_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def _asset_path(self, asset_hash: str) -> Path:
        return self.assets_dir / asset_hash[:2] / asset_hash

    def is_cached(self, asset_hash: str) -> bool:
        return self._asset_path(asset_hash).exists()

    def _current_size(self) -> int:
        return sum(int(item.get("size", 0)) for item in self._index.values())

    def _touch_index_record_locked(
        self,
        *,
        asset_hash: str,
        size: int,
        last_access: float,
        pin_task_id: str | None,
    ) -> None:
        record = self._index.get(asset_hash) or {}
        record["last_access"] = float(last_access)
        record["size"] = int(size)
        if pin_task_id:
            record["pin_task_id"] = pin_task_id
        self._index[asset_hash] = record
        self._index_version += 1

    def _evict_if_needed_locked(
        self,
        protected: set[str] | None = None,
        active_task_id: str | None = None,
    ) -> None:
        protected = protected or set()
        pinned_id = active_task_id
        total = self._current_size()
        if total <= self.max_bytes:
            return

        victims = sorted(
            [
                (asset_hash, data)
                for asset_hash, data in self._index.items()
                if asset_hash not in protected and (
                    not pinned_id
                    or str(data.get("pin_task_id") or "") != pinned_id
                )
            ],
            key=lambda item: float(item[1].get("last_access", 0)),
        )
        for asset_hash, data in victims:
            if total <= self.max_bytes:
                break
            path = self._asset_path(asset_hash)
            if path.exists():
                try:
                    os.remove(path)
                except Exception:
                    pass
            total -= int(data.get("size", 0))
            self._index.pop(asset_hash, None)
            self._index_version += 1

    async def flush_index(self, *, force: bool = False) -> tuple[int, float]:
        async with self._state_lock:
            if not force and self._flushed_index_version >= self._index_version:
                return 0, 0.0
            snapshot = self._build_index_snapshot(self._index)
            target_version = self._index_version

        started_at = time.perf_counter()
        await asyncio.to_thread(
            self._write_index_snapshot,
            self.index_path,
            snapshot,
        )
        elapsed = time.perf_counter() - started_at

        async with self._state_lock:
            self._flushed_index_version = max(self._flushed_index_version, target_version)
        return 1, elapsed

    async def aclose(self) -> None:
        await self.flush_index(force=True)
        async with self._client_lock:
            client = self._client
            self._client = None
        if client is not None:
            await client.aclose()

    async def ensure_cached(
        self,
        asset_hash: str,
        download_url: str,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback: AssetProgressFn | None = None,
    ) -> Path:
        result = await self.ensure_cached_batch(
            [(asset_hash, download_url)],
            protected=protected,
            pin_task_id=pin_task_id,
            progress_callback=progress_callback,
        )
        path = result.paths.get(asset_hash)
        if path is None:
            raise FileNotFoundError(f"cached asset path missing: {asset_hash}")
        return path

    async def ensure_cached_batch(
        self,
        items: list[tuple[str, str]],
        *,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback: AssetProgressFn | None = None,
        yield_every: int = _CACHE_BATCH_YIELD_EVERY,
    ) -> CacheBatchResult:
        paths: dict[str, Path] = {}
        if not items:
            return CacheBatchResult(
                paths=paths,
                cache_hits=0,
                cache_misses=0,
                lookup_sec=0.0,
                flush_sec=0.0,
                dirty_entries=0,
                flush_count=0,
            )

        deduped: dict[str, str] = {}
        for asset_hash, download_url in items:
            asset_hash_text = str(asset_hash or "").strip()
            download_url_text = str(download_url or "").strip()
            if not asset_hash_text or not download_url_text:
                continue
            deduped.setdefault(asset_hash_text, download_url_text)

        if not deduped:
            return CacheBatchResult(
                paths=paths,
                cache_hits=0,
                cache_misses=0,
                lookup_sec=0.0,
                flush_sec=0.0,
                dirty_entries=0,
                flush_count=0,
            )

        protected_set = set(protected or set())
        cache_hits = 0
        cache_misses = 0
        dirty_entries = 0
        yielded = 0
        lookup_started_at = time.perf_counter()
        hit_updates: list[tuple[str, Path, int, float]] = []
        miss_items: list[tuple[str, str]] = []

        for asset_hash, download_url in deduped.items():
            path = self._asset_path(asset_hash)
            if path.exists():
                stat = path.stat()
                hit_updates.append((asset_hash, path, int(stat.st_size), time.time()))
                self._emit_progress(
                    progress_callback,
                    {
                        "event": "cache_hit",
                        "asset_hash": asset_hash,
                        "size": int(stat.st_size),
                    },
                )
                paths[asset_hash] = path
                cache_hits += 1
            else:
                miss_items.append((asset_hash, download_url))
                cache_misses += 1
            yielded += 1
            if yielded % max(1, int(yield_every or 1)) == 0:
                self._mark_activity("asset_cache.batch_lookup")
                await asyncio.sleep(0)

        if hit_updates:
            async with self._state_lock:
                for asset_hash, _path, size, touched_at in hit_updates:
                    self._touch_index_record_locked(
                        asset_hash=asset_hash,
                        size=size,
                        last_access=touched_at,
                        pin_task_id=pin_task_id,
                    )
                    dirty_entries += 1
            self._mark_activity("asset_cache.cache_hit_batch")

        miss_results = await self._ensure_misses_cached(
            miss_items=miss_items,
            protected=protected_set,
            pin_task_id=pin_task_id,
            progress_callback=progress_callback,
        )
        paths.update(miss_results)
        lookup_sec = time.perf_counter() - lookup_started_at
        flush_count, flush_sec = await self.flush_index(force=False)
        return CacheBatchResult(
            paths=paths,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            lookup_sec=lookup_sec,
            flush_sec=flush_sec,
            dirty_entries=dirty_entries + cache_misses,
            flush_count=flush_count,
        )

    async def _ensure_misses_cached(
        self,
        *,
        miss_items: list[tuple[str, str]],
        protected: set[str],
        pin_task_id: str | None,
        progress_callback: AssetProgressFn | None,
    ) -> dict[str, Path]:
        if not miss_items:
            return {}

        tasks: dict[str, tuple[asyncio.Task[Path], bool]] = {}
        for asset_hash, download_url in miss_items:
            task, owner = await self._get_or_create_inflight_download(
                asset_hash=asset_hash,
                download_url=download_url,
                protected=protected,
                pin_task_id=pin_task_id,
                progress_callback=progress_callback,
            )
            tasks[asset_hash] = (task, owner)

        resolved: dict[str, Path] = {}
        try:
            for asset_hash, (task, owner) in tasks.items():
                path = await task
                resolved[asset_hash] = path
                if not owner:
                    stat = path.stat()
                    self._emit_progress(
                        progress_callback,
                        {
                            "event": "inflight_join",
                            "asset_hash": asset_hash,
                            "size": int(stat.st_size),
                        },
                    )
        finally:
            for asset_hash, (task, owner) in tasks.items():
                if not owner:
                    continue
                async with self._inflight_lock:
                    current = self._inflight.get(asset_hash)
                    if current is task:
                        self._inflight.pop(asset_hash, None)
        return resolved

    async def _get_or_create_inflight_download(
        self,
        *,
        asset_hash: str,
        download_url: str,
        protected: set[str] | None,
        pin_task_id: str | None,
        progress_callback: AssetProgressFn | None,
    ) -> tuple[asyncio.Task[Path], bool]:
        async with self._inflight_lock:
            inflight = self._inflight.get(asset_hash)
            if inflight is None:
                inflight = asyncio.create_task(
                    self._download_asset(
                        asset_hash=asset_hash,
                        download_url=download_url,
                        protected=protected,
                        pin_task_id=pin_task_id,
                        progress_callback=progress_callback,
                    ),
                    name=f"asset-cache:{asset_hash}",
                )
                self._inflight[asset_hash] = inflight
                return inflight, True
            return inflight, False

    async def _download_asset(
        self,
        *,
        asset_hash: str,
        download_url: str,
        protected: set[str] | None,
        pin_task_id: str | None,
        progress_callback: AssetProgressFn | None,
    ) -> Path:
        path = self._asset_path(asset_hash)
        now = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp-{asyncio.current_task().get_name() if asyncio.current_task() else 'download'}")
        hasher = hashlib.sha256()
        written_bytes = 0
        self._emit_progress(
            progress_callback,
            {
                "event": "download_started",
                "asset_hash": asset_hash,
            },
        )
        self._mark_activity("asset_cache.download_started")
        try:
            async with self._download_semaphore:
                client = await self._get_client()
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    content_length = self._parse_content_length(response.headers.get("content-length"))
                    self._emit_progress(
                        progress_callback,
                        {
                            "event": "download_response",
                            "asset_hash": asset_hash,
                            "content_length": content_length,
                        },
                    )
                    with tmp.open("wb") as file_obj:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            hasher.update(chunk)
                            written_bytes += len(chunk)
                            self._mark_activity("asset_cache.download_progress")
                            self._emit_progress(
                                progress_callback,
                                {
                                    "event": "download_progress",
                                    "asset_hash": asset_hash,
                                    "bytes_delta": len(chunk),
                                    "written_bytes": written_bytes,
                                    "content_length": content_length,
                                },
                            )

            digest = hasher.hexdigest()
            if digest != asset_hash:
                raise ValueError(f"asset hash mismatch: expect={asset_hash}, actual={digest}")

            tmp.rename(path)
            async with self._state_lock:
                self._touch_index_record_locked(
                    asset_hash=asset_hash,
                    size=path.stat().st_size,
                    last_access=now,
                    pin_task_id=pin_task_id,
                )
                self._evict_if_needed_locked(
                    protected=protected,
                    active_task_id=pin_task_id,
                )
            final_size = int(path.stat().st_size)
            self._mark_activity("asset_cache.download_completed")
            self._emit_progress(
                progress_callback,
                {
                    "event": "download_completed",
                    "asset_hash": asset_hash,
                    "size": final_size,
                },
            )
            return path
        except BaseException as exc:
            with suppress(Exception):
                tmp.unlink(missing_ok=True)
            self._mark_activity("asset_cache.download_failed")
            self._emit_progress(
                progress_callback,
                {
                    "event": "download_failed",
                    "asset_hash": asset_hash,
                    "written_bytes": written_bytes,
                    "error": str(exc),
                },
            )
            raise

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._client_lock:
            if self._client is None:
                limits = httpx.Limits(
                    max_connections=max(32, self._download_concurrency * 4),
                    max_keepalive_connections=max(16, self._download_concurrency * 2),
                )
                self._client = httpx.AsyncClient(
                    timeout=self._http_timeout_sec,
                    limits=limits,
                )
            return self._client

    @staticmethod
    def _emit_progress(callback: AssetProgressFn | None, payload: dict[str, Any]) -> None:
        if callback is not None:
            with suppress(Exception):
                callback(payload)

    def _mark_activity(self, source: str) -> None:
        if self._activity_callback is not None:
            self._activity_callback(source)

    @staticmethod
    def _parse_content_length(value: str | None) -> int | None:
        try:
            parsed = int(str(value or "").strip())
        except Exception:
            return None
        return parsed if parsed >= 0 else None
