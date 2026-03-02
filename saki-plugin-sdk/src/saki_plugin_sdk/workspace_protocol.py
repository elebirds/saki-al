from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class WorkspaceProtocol(Protocol):
    step_id: str
    root: Path
    config_path: Path
    events_path: Path
    artifacts_dir: Path
    data_dir: Path
    cache_dir: Path

    def ensure(self) -> None:
        ...
