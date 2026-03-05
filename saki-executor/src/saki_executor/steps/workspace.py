from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Workspace:
    def __init__(
        self,
        runs_dir: str,
        task_id: str,
        *,
        round_id: str = "",
        attempt: int = 1,
    ):
        self.task_id = str(task_id or "").strip()
        self.runs_root = Path(runs_dir)
        self.round_id = str(round_id or "").strip()
        self.attempt = max(1, int(attempt or 1))

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

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.shared_models_dir.mkdir(parents=True, exist_ok=True)
        self.shared_data_cache_dir.mkdir(parents=True, exist_ok=True)
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
