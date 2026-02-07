from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from saki_runtime.schemas.enums import EventType, JobStatus


class LogPayload(BaseModel):
    level: str
    message: str
    logger: Optional[str] = None


class ProgressPayload(BaseModel):
    epoch: int
    step: int
    total_steps: int
    eta_sec: Optional[int] = None


class MetricPayload(BaseModel):
    step: int
    metrics: Dict[str, float]
    epoch: Optional[int] = None


class ArtifactPayload(BaseModel):
    kind: str
    name: str
    uri: str
    meta: Optional[Dict[str, Any]] = None


class StatusPayload(BaseModel):
    status: JobStatus
    reason: Optional[str] = None


class EventEnvelope(BaseModel):
    job_id: str
    seq: int = Field(..., ge=1)
    ts: int
    type: EventType
    payload: Dict[str, Any]
