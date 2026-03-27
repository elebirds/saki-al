from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saki_executor.cache.prepared_data_cache import PreparedDataCache
from saki_executor.core.config import settings


def _normalize_root_path(path: str) -> Path:
    root = Path(str(path or "")).expanduser()
    try:
        return root.resolve()
    except Exception:
        return root.absolute()


def _link_or_copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def _link_or_copy_tree(src_root: Path, dst_root: Path) -> None:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    for path in src_root.rglob("*"):
        rel = path.relative_to(src_root)
        target = dst_root / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.symlink_to(path.readlink())
            except Exception:
                shutil.copy2(path, target)
            continue
        _link_or_copy_file(path, target)


class Workspace:
    def __init__(
        self,
        runs_dir: str,
        task_id: str,
        *,
        round_id: str = "",
        attempt: int = 1,
        prepared_data_cache_root: str | Path | None = None,
    ):
        self.task_id = str(task_id or "").strip()
        self.runs_root = _normalize_root_path(runs_dir)
        self.round_id = str(round_id or "").strip()
        self.attempt = max(1, int(attempt or 1))
        self._prepared_data_cache_root = (
            _normalize_root_path(str(prepared_data_cache_root))
            if prepared_data_cache_root
            else None
        )

        if self.round_id:
            self.round_root = self.runs_root / "rounds" / self.round_id / f"attempt_{self.attempt}"
            self.steps_root = self.round_root / "steps"
            self.root = self.steps_root / self.task_id
        else:
            self.round_root = None
            self.steps_root = None
            self.root = self.runs_root / self.task_id

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def shared_dir(self) -> Path:
        if self.round_root is None:
            return self.root / "shared"
        return self.round_root / "shared"

    @property
    def shared_models_dir(self) -> Path:
        return self.shared_dir / "models"

    @property
    def shared_data_cache_dir(self) -> Path:
        return self.shared_dir / "data_cache"

    @property
    def round_manifest_path(self) -> Path:
        return self.shared_dir / "round_manifest.json"

    @property
    def prepared_data_cache_dir(self) -> Path | None:
        return self._prepared_data_cache_root

    def _prepared_data_cache(self) -> PreparedDataCache | None:
        if self.prepared_data_cache_dir is None:
            return None
        return PreparedDataCache(
            self.prepared_data_cache_dir,
            max_bytes=settings.PREPARED_DATA_CACHE_MAX_BYTES,
            max_age_hours=settings.PREPARED_DATA_CACHE_MAX_AGE_HOURS,
        )

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.shared_models_dir.mkdir(parents=True, exist_ok=True)
        self.shared_data_cache_dir.mkdir(parents=True, exist_ok=True)
        if self.prepared_data_cache_dir is not None:
            self.prepared_data_cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            self.events_path.touch()
        self._ensure_round_manifest()

    def write_config(self, payload: dict[str, Any]) -> None:
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def link_shared_model_to_step(self, artifact_name: str) -> Path | None:
        name = str(artifact_name or "").strip()
        if not name:
            return None
        source = self.shared_models_dir / name
        if not source.exists():
            return None
        target = self.artifacts_dir / name
        if target.exists():
            return target
        try:
            rel_target = Path(
                source.relative_to(target.parent)
            ) if source.is_relative_to(target.parent) else source  # py311+
        except Exception:
            rel_target = source
        try:
            target.symlink_to(rel_target)
        except Exception:
            shutil.copy2(source, target)
        return target

    def cache_model_artifact(self, artifact_name: str, source_path: Path, source_task_id: str) -> Path:
        name = str(artifact_name or "").strip()
        if not name:
            raise ValueError("artifact_name is required")
        if not source_path.exists():
            raise FileNotFoundError(f"model artifact not found: {source_path}")
        self.shared_models_dir.mkdir(parents=True, exist_ok=True)
        target = self.shared_models_dir / name
        shutil.copy2(source_path, target)

        manifest = self.read_round_manifest()
        models = manifest.get("models", {})
        if not isinstance(models, dict):
            models = {}
        models[name] = {
            "source_task_id": str(source_task_id or self.task_id),
            "path": str(target),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        manifest["models"] = models
        self.write_round_manifest(manifest)
        return target

    def restore_shared_data_cache(self, fingerprint: str) -> bool:
        cache_path = self.shared_data_cache_dir / str(fingerprint or "").strip()
        if not cache_path.exists() or not cache_path.is_dir():
            return False
        if self.data_dir.exists():
            shutil.rmtree(self.data_dir)
        shutil.copytree(cache_path, self.data_dir)
        return True

    def store_shared_data_cache(self, fingerprint: str, source_task_id: str, task_type: str) -> Path:
        key = str(fingerprint or "").strip()
        if not key:
            raise ValueError("fingerprint is required")
        if not self.data_dir.exists():
            raise FileNotFoundError(f"task data dir not found: {self.data_dir}")

        self.shared_data_cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.shared_data_cache_dir / key
        tmp = self.shared_data_cache_dir / f".{key}.tmp-{uuid.uuid4().hex}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(self.data_dir, tmp)
        if target.exists():
            shutil.rmtree(target)
        tmp.rename(target)

        manifest = self.read_round_manifest()
        data_cache = manifest.get("data_cache", {})
        if not isinstance(data_cache, dict):
            data_cache = {}
        data_cache[key] = {
            "source_task_id": str(source_task_id or self.task_id),
            "task_type": str(task_type or ""),
            "path": str(target),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        manifest["data_cache"] = data_cache
        self.write_round_manifest(manifest)
        return target

    def restore_prepared_data_cache(self, fingerprint: str) -> bool:
        cache_root = self.prepared_data_cache_dir
        if cache_root is None:
            return False
        cache_path = cache_root / str(fingerprint or "").strip()
        if not cache_path.exists() or not cache_path.is_dir():
            return False
        _link_or_copy_tree(cache_path, self.data_dir)
        prepared_cache = self._prepared_data_cache()
        if prepared_cache is not None:
            prepared_cache.touch(str(fingerprint or "").strip())
        return True

    def store_prepared_data_cache(self, fingerprint: str, source_task_id: str) -> Path:
        cache_root = self.prepared_data_cache_dir
        if cache_root is None:
            raise RuntimeError("prepared data cache root is not configured")
        key = str(fingerprint or "").strip()
        if not key:
            raise ValueError("fingerprint is required")
        if not self.data_dir.exists():
            raise FileNotFoundError(f"task data dir not found: {self.data_dir}")

        cache_root.mkdir(parents=True, exist_ok=True)
        target = cache_root / key
        prepared_cache = self._prepared_data_cache()
        if target.exists() and target.is_dir():
            if prepared_cache is not None:
                prepared_cache.register(key, source_task_id=str(source_task_id or self.task_id))
                prepared_cache.prune(protected={key})
            return target

        tmp = cache_root / f".{key}.tmp-{uuid.uuid4().hex}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(self.data_dir, tmp)
        try:
            tmp.rename(target)
        except FileExistsError:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if prepared_cache is not None:
            prepared_cache.register(key, source_task_id=str(source_task_id or self.task_id))
            prepared_cache.prune(protected={key})
        return target

    def read_round_manifest(self) -> dict[str, Any]:
        self._ensure_round_manifest()
        try:
            payload = json.loads(self.round_manifest_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else self._default_round_manifest()
        except Exception:
            return self._default_round_manifest()

    def write_round_manifest(self, payload: dict[str, Any]) -> None:
        self.round_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.round_manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _default_round_manifest(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "attempt": self.attempt,
            "models": {},
            "data_cache": {},
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def _ensure_round_manifest(self) -> None:
        if self.round_manifest_path.exists():
            return
        self.write_round_manifest(self._default_round_manifest())
