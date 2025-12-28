import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from saki_runtime.core.event_store import EventStore


class Workspace:
    def __init__(self, root_runs_dir: str, job_id: str):
        self.root = Path(root_runs_dir)
        self.job_id = job_id
        self._workdir = self.root / self.job_id

    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def config_path(self) -> Path:
        return self._workdir / "config.json"

    @property
    def events_path(self) -> Path:
        return self._workdir / "events.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self._workdir / "artifacts"

    @property
    def cache_dir(self) -> Path:
        return self._workdir / "cache"

    @property
    def data_dir(self) -> Path:
        return self._workdir / "data"

    def ensure_created(self) -> None:
        """Idempotently create the workspace directory structure."""
        try:
            self.workdir.mkdir(parents=True, exist_ok=True)
            self.artifacts_dir.mkdir(exist_ok=True)
            self.cache_dir.mkdir(exist_ok=True)
            self.data_dir.mkdir(exist_ok=True)
            
            # Ensure events file exists
            if not self.events_path.exists():
                self.events_path.touch()
                
            logger.info(f"Workspace ensured for job {self.job_id} at {self.workdir}")
        except Exception as e:
            logger.error(f"Failed to create workspace for job {self.job_id}: {e}")
            raise

    def write_config(self, config: Dict[str, Any]) -> None:
        """Write job configuration to config.json."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def load_config(self) -> Optional[Dict[str, Any]]:
        """Load job configuration from config.json."""
        if not self.config_path.exists():
            return None
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_event_store(self) -> EventStore:
        """Get the EventStore for this workspace."""
        return EventStore(self.events_path)

    def clean(self) -> None:
        """Remove the workspace directory."""
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
