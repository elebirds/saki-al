import json
import time
from typing import Any, Dict, Optional

from saki_runtime.core.event_store import EventStore
from saki_runtime.schemas.enums import EventType, JobStatus
from saki_runtime.schemas.events import (
    ArtifactPayload,
    EventEnvelope,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    StatusPayload,
)


class JobReporter:
    def __init__(self, events_path: str, job_id: str):
        # Path object conversion handled in EventStore if needed, but it expects Path
        from pathlib import Path
        self.store = EventStore(Path(events_path))
        self.job_id = job_id

    def _append(self, type: EventType, payload: Dict[str, Any]) -> None:
        event = EventEnvelope(
            job_id=self.job_id,
            seq=self.store.next_seq(),
            ts=int(time.time()),
            type=type,
            payload=payload,
        )
        self.store.append(event)

    def log(self, message: str, level: str = "INFO", logger: Optional[str] = None) -> None:
        self._append(
            EventType.LOG,
            LogPayload(level=level, message=message, logger=logger).model_dump(),
        )

    def progress(self, percentage: float, message: Optional[str] = None, eta_seconds: Optional[float] = None) -> None:
        self._append(
            EventType.PROGRESS,
            ProgressPayload(percentage=percentage, message=message, eta_seconds=eta_seconds).model_dump(),
        )

    def metric(self, step: int, metrics: Dict[str, float], epoch: Optional[int] = None) -> None:
        self._append(
            EventType.METRIC,
            MetricPayload(step=step, metrics=metrics, epoch=epoch).model_dump(),
        )

    def artifact(self, name: str, path: str, type: str, size_bytes: Optional[int] = None) -> None:
        self._append(
            EventType.ARTIFACT,
            ArtifactPayload(name=name, path=path, type=type, size_bytes=size_bytes).model_dump(),
        )

    def status(self, current: JobStatus, previous: JobStatus, message: Optional[str] = None) -> None:
        self._append(
            EventType.STATUS,
            StatusPayload(current_status=current, previous_status=previous, message=message).model_dump(),
        )
