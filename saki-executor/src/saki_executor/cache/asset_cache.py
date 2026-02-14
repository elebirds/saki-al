import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx


class AssetCache:
    def __init__(self, root_dir: str, max_bytes: int):
        self.root = Path(root_dir)
        self.max_bytes = max_bytes
        self.assets_dir = self.root / "assets"
        self.index_path = self.root / "cache_index.json"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()

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

    def _current_size(self) -> int:
        return sum(int(item.get("size", 0)) for item in self._index.values())

    def _evict_if_needed(
            self,
            protected: set[str] | None = None,
            active_step_id: str | None = None,
    ) -> None:
        protected = protected or set()
        total = self._current_size()
        if total <= self.max_bytes:
            return

        victims = sorted(
            [
                (asset_hash, data)
                for asset_hash, data in self._index.items()
                if asset_hash not in protected and (
                    not active_step_id or str(data.get("pin_step_id") or "") != active_step_id
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

    async def ensure_cached(
            self,
            asset_hash: str,
            download_url: str,
            protected: set[str] | None = None,
            pin_step_id: str | None = None,
    ) -> Path:
        path = self._asset_path(asset_hash)
        now = time.time()

        if path.exists():
            record = self._index.get(asset_hash) or {}
            record["last_access"] = now
            record["size"] = path.stat().st_size
            if pin_step_id:
                record["pin_step_id"] = pin_step_id
            self._index[asset_hash] = record
            self._save_index()
            return path

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")

        hasher = hashlib.sha256()
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", download_url) as response:
                response.raise_for_status()
                with tmp.open("wb") as file_obj:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        hasher.update(chunk)

        digest = hasher.hexdigest()
        if digest != asset_hash:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"asset hash mismatch: expect={asset_hash}, actual={digest}")

        tmp.rename(path)
        self._index[asset_hash] = {
            "size": path.stat().st_size,
            "last_access": now,
            "pin_step_id": pin_step_id,
        }
        self._evict_if_needed(protected=protected, active_step_id=pin_step_id)
        self._save_index()
        return path
