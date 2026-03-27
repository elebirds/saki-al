from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from saki_executor.cache.prepared_data_cache import PreparedDataCache


def _write_payload(path: Path, size: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.bin").write_bytes(b"x" * size)


def test_prepared_data_cache_touch_updates_last_access(tmp_path: Path) -> None:
    root = tmp_path / "cache" / "prepared_data_v2"
    cache = PreparedDataCache(root, max_bytes=1024, max_age_hours=24)
    _write_payload(root / "fp-1", 16)

    created_at = datetime(2026, 3, 27, 0, 0, tzinfo=UTC)
    accessed_at = created_at + timedelta(minutes=5)
    cache.register("fp-1", source_task_id="task-1", now=created_at)

    assert cache.touch("fp-1", now=accessed_at) is True

    snapshot = cache.read_index()
    assert snapshot["fp-1"]["created_at"] == created_at.isoformat()
    assert snapshot["fp-1"]["last_access_at"] == accessed_at.isoformat()
    assert snapshot["fp-1"]["size_bytes"] == 16


def test_prepared_data_cache_prune_removes_expired_entries(tmp_path: Path) -> None:
    root = tmp_path / "cache" / "prepared_data_v2"
    cache = PreparedDataCache(root, max_bytes=1024, max_age_hours=24)
    _write_payload(root / "expired", 8)
    _write_payload(root / "fresh", 8)

    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    cache.register("expired", source_task_id="task-old", now=now - timedelta(hours=25))
    cache.register("fresh", source_task_id="task-new", now=now - timedelta(hours=2))

    result = cache.prune(now=now)

    assert result.deleted_fingerprints == ["expired"]
    assert not (root / "expired").exists()
    assert (root / "fresh").exists()
    assert "expired" not in cache.read_index()


def test_prepared_data_cache_prune_evicts_lru_when_over_capacity(tmp_path: Path) -> None:
    root = tmp_path / "cache" / "prepared_data_v2"
    cache = PreparedDataCache(root, max_bytes=10, max_age_hours=24)
    _write_payload(root / "older", 8)
    _write_payload(root / "newer", 8)

    base = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    cache.register("older", source_task_id="task-1", now=base - timedelta(hours=3))
    cache.register("newer", source_task_id="task-2", now=base - timedelta(hours=1))

    result = cache.prune(now=base, protected={"newer"})

    assert result.deleted_fingerprints == ["older"]
    assert not (root / "older").exists()
    assert (root / "newer").exists()


def test_prepared_data_cache_prune_cleans_tmp_dirs_and_orphan_index(tmp_path: Path) -> None:
    root = tmp_path / "cache" / "prepared_data_v2"
    cache = PreparedDataCache(root, max_bytes=1024, max_age_hours=24)
    _write_payload(root / "kept", 8)
    (root / ".kept.tmp-deadbeef").mkdir(parents=True, exist_ok=True)
    cache.register("kept", source_task_id="task-1", now=datetime(2026, 3, 27, 0, 0, tzinfo=UTC))

    index_path = root / "cache_index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["missing"] = {
        "path": str(root / "missing"),
        "size_bytes": 10,
        "created_at": datetime(2026, 3, 26, 0, 0, tzinfo=UTC).isoformat(),
        "last_access_at": datetime(2026, 3, 26, 0, 0, tzinfo=UTC).isoformat(),
        "source_task_id": "task-missing",
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = cache.prune(now=datetime(2026, 3, 27, 12, 0, tzinfo=UTC))

    assert ".kept.tmp-deadbeef" in result.deleted_tmp_dirs
    assert "missing" in result.repaired_fingerprints
    assert not (root / ".kept.tmp-deadbeef").exists()
    assert "missing" not in cache.read_index()
