from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VenvCacheKey:
    plugin_id: str
    plugin_version: str
    profile_id: str
    lock_hash: str
    py_version: str
    platform_arch: str

    def cache_id(self) -> str:
        return (
            f"{self.plugin_id}:{self.plugin_version}:{self.profile_id}:"
            f"{self.lock_hash}:{self.py_version}:{self.platform_arch}"
        )


def resolve_lock_hash(plugin_dir: Path) -> str:
    lock_file = plugin_dir / "uv.lock"
    if not lock_file.exists():
        return "no-lock"
    try:
        stat = lock_file.stat()
        return f"{int(stat.st_mtime)}-{int(stat.st_size)}"
    except Exception:
        return "lock-unknown"
