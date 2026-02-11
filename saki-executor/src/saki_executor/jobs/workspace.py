import json
from pathlib import Path
from typing import Any


class Workspace:
    def __init__(self, runs_dir: str, job_id: str):
        self.job_id = job_id
        self.root = Path(runs_dir) / job_id

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
