import asyncio
import hashlib
import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

import httpx

AssetProgressFn = Callable[[dict[str, Any]], None]
ActivityFn = Callable[[str], None]


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

    def _asset_path(self, asset_hash: str) -> Path:
        return self.assets_dir / asset_hash[:2] / asset_hash

    def is_cached(self, asset_hash: str) -> bool:
        return self._asset_path(asset_hash).exists()

    def _current_size(self) -> int:
        return sum(int(item.get("size", 0)) for item in self._index.values())

    def _evict_if_needed(
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
        self._save_index()

    async def aclose(self) -> None:
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
        path = self._asset_path(asset_hash)
        now = time.time()
        pinned_id = pin_task_id

        if path.exists():
            stat = path.stat()
            async with self._state_lock:
                record = self._index.get(asset_hash) or {}
                record["last_access"] = now
                record["size"] = stat.st_size
                if pinned_id:
                    record["pin_task_id"] = pinned_id
                self._index[asset_hash] = record
                self._save_index()
            self._emit_progress(
                progress_callback,
                {
                    "event": "cache_hit",
                    "asset_hash": asset_hash,
                    "size": int(stat.st_size),
                },
            )
            return path

        async with self._inflight_lock:
            inflight = self._inflight.get(asset_hash)
            if inflight is None:
                inflight = asyncio.create_task(
                    self._download_asset(
                        asset_hash=asset_hash,
                        download_url=download_url,
                        protected=protected,
                        pin_task_id=pinned_id,
                        progress_callback=progress_callback,
                    ),
                    name=f"asset-cache:{asset_hash}",
                )
                self._inflight[asset_hash] = inflight
                owner = True
            else:
                owner = False

        try:
            path = await inflight
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
            return path
        finally:
            if owner:
                async with self._inflight_lock:
                    current = self._inflight.get(asset_hash)
                    if current is inflight:
                        self._inflight.pop(asset_hash, None)

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
                self._index[asset_hash] = {
                    "size": path.stat().st_size,
                    "last_access": now,
                    "pin_task_id": pin_task_id,
                }
                self._evict_if_needed(
                    protected=protected,
                    active_task_id=pin_task_id,
                )
                self._save_index()
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
