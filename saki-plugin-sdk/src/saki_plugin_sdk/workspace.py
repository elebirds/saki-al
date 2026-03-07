import json
from pathlib import Path
from typing import Any


def _normalize_root_path(path: str) -> Path:
    root = Path(str(path or "")).expanduser()
    try:
        return root.resolve()
    except Exception:
        return root.absolute()


class Workspace:
    """Manages a step's working directory layout under ``runs/{task_id}``."""

    def __init__(self, runs_dir: str, task_id: str):
        self.task_id = task_id
        self.runs_root = _normalize_root_path(runs_dir)
        self.root = self.runs_root / task_id

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

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            self.events_path.touch()

    def write_config(self, payload: dict[str, Any]) -> None:
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
