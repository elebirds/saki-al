from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[str, threading.Lock] = {}


def _get_root_lock(root_dir: Path) -> threading.Lock:
    key = str(root_dir)
    with _LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ROOT_LOCKS[key] = lock
        return lock


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


@dataclass
class PreparedDataCachePruneResult:
    deleted_fingerprints: list[str] = field(default_factory=list)
    repaired_fingerprints: list[str] = field(default_factory=list)
    deleted_tmp_dirs: list[str] = field(default_factory=list)


class PreparedDataCache:
    def __init__(self, root_dir: str | Path, *, max_bytes: int, max_age_hours: int) -> None:
        self.root = Path(root_dir).expanduser()
        self.max_bytes = max(0, int(max_bytes or 0))
        self.max_age_hours = max(0, int(max_age_hours or 0))
        self.index_path = self.root / "cache_index.json"
        self._lock = _get_root_lock(self.root)

    def read_index(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._load_index_unlocked()

    def register(
        self,
        fingerprint: str,
        *,
        source_task_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        key = str(fingerprint or "").strip()
        if not key:
            raise ValueError("fingerprint is required")
        path = self.root / key
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"prepared data cache not found: {path}")

        current = now or _utc_now()
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            index = self._load_index_unlocked()
            previous = index.get(key) if isinstance(index.get(key), dict) else {}
            created_at = _parse_dt(previous.get("created_at")) or current
            entry = self._build_entry(
                path=path,
                source_task_id=str(source_task_id or previous.get("source_task_id") or ""),
                created_at=created_at,
                last_access_at=current,
            )
            index[key] = entry
            self._save_index_unlocked(index)
            return dict(entry)

    def touch(self, fingerprint: str, *, now: datetime | None = None) -> bool:
        key = str(fingerprint or "").strip()
        if not key:
            return False

        current = now or _utc_now()
        path = self.root / key
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            index = self._load_index_unlocked()
            previous = index.get(key) if isinstance(index.get(key), dict) else {}
            if not path.exists() or not path.is_dir():
                if key in index:
                    index.pop(key, None)
                    self._save_index_unlocked(index)
                return False

            created_at = _parse_dt(previous.get("created_at")) or self._infer_path_time(path)
            entry = self._build_entry(
                path=path,
                source_task_id=str(previous.get("source_task_id") or ""),
                created_at=created_at,
                last_access_at=current,
            )
            index[key] = entry
            self._save_index_unlocked(index)
            return True

    def prune(
        self,
        *,
        protected: set[str] | None = None,
        now: datetime | None = None,
    ) -> PreparedDataCachePruneResult:
        protected = {str(item or "").strip() for item in (protected or set()) if str(item or "").strip()}
        current = now or _utc_now()
        result = PreparedDataCachePruneResult()

        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            index = self._load_index_unlocked()
            self._cleanup_tmp_dirs_unlocked(result)
            self._sync_index_with_disk_unlocked(index=index, result=result)
            self._prune_expired_unlocked(index=index, protected=protected, now=current, result=result)
            self._prune_oversized_unlocked(index=index, protected=protected, result=result)
            self._save_index_unlocked(index)

        return result

    def _cleanup_tmp_dirs_unlocked(self, result: PreparedDataCachePruneResult) -> None:
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            if not child.name.startswith(".") or ".tmp-" not in child.name:
                continue
            shutil.rmtree(child, ignore_errors=True)
            result.deleted_tmp_dirs.append(child.name)

    def _sync_index_with_disk_unlocked(
        self,
        *,
        index: dict[str, dict[str, Any]],
        result: PreparedDataCachePruneResult,
    ) -> None:
        existing_dirs: dict[str, Path] = {}
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            existing_dirs[child.name] = child

        for fingerprint in list(index.keys()):
            path = existing_dirs.get(fingerprint)
            if path is not None:
                continue
            index.pop(fingerprint, None)
            result.repaired_fingerprints.append(fingerprint)

        for fingerprint, path in existing_dirs.items():
            previous = index.get(fingerprint) if isinstance(index.get(fingerprint), dict) else {}
            if previous:
                continue
            inferred_at = self._infer_path_time(path)
            index[fingerprint] = self._build_entry(
                path=path,
                source_task_id="",
                created_at=inferred_at,
                last_access_at=inferred_at,
            )

    def _prune_expired_unlocked(
        self,
        *,
        index: dict[str, dict[str, Any]],
        protected: set[str],
        now: datetime,
        result: PreparedDataCachePruneResult,
    ) -> None:
        if self.max_age_hours <= 0:
            return
        expire_before = now - timedelta(hours=self.max_age_hours)
        for fingerprint, entry in list(index.items()):
            if fingerprint in protected:
                continue
            last_access_at = _parse_dt(entry.get("last_access_at")) or _parse_dt(entry.get("created_at"))
            if last_access_at is None or last_access_at > expire_before:
                continue
            self._delete_entry_unlocked(fingerprint=fingerprint, entry=entry, index=index, result=result)

    def _prune_oversized_unlocked(
        self,
        *,
        index: dict[str, dict[str, Any]],
        protected: set[str],
        result: PreparedDataCachePruneResult,
    ) -> None:
        if self.max_bytes <= 0:
            return
        total = sum(int((entry or {}).get("size_bytes", 0)) for entry in index.values())
        if total <= self.max_bytes:
            return

        victims = sorted(
            (
                (fingerprint, entry)
                for fingerprint, entry in index.items()
                if fingerprint not in protected
            ),
            key=lambda item: _parse_dt((item[1] or {}).get("last_access_at")) or _parse_dt((item[1] or {}).get("created_at")) or datetime.fromtimestamp(0, tz=UTC),
        )
        for fingerprint, entry in victims:
            if total <= self.max_bytes:
                break
            total -= int((entry or {}).get("size_bytes", 0))
            self._delete_entry_unlocked(fingerprint=fingerprint, entry=entry, index=index, result=result)

    def _delete_entry_unlocked(
        self,
        *,
        fingerprint: str,
        entry: dict[str, Any],
        index: dict[str, dict[str, Any]],
        result: PreparedDataCachePruneResult,
    ) -> None:
        path = Path(str(entry.get("path") or self.root / fingerprint))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        index.pop(fingerprint, None)
        result.deleted_fingerprints.append(fingerprint)

    def _build_entry(
        self,
        *,
        path: Path,
        source_task_id: str,
        created_at: datetime,
        last_access_at: datetime,
    ) -> dict[str, Any]:
        return {
            "path": str(path),
            "size_bytes": self._dir_size(path),
            "created_at": _as_iso(created_at),
            "last_access_at": _as_iso(last_access_at),
            "source_task_id": str(source_task_id or ""),
        }

    def _infer_path_time(self, path: Path) -> datetime:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except Exception:
            return _utc_now()

    def _load_index_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        snapshot: dict[str, dict[str, Any]] = {}
        for key, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            snapshot[str(key)] = dict(entry)
        return snapshot

    def _save_index_unlocked(self, index: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _dir_size(self, root: Path) -> int:
        total = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                total += path.stat().st_size
            except Exception:
                continue
        return total
