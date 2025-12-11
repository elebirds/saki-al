from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from saki_runtime.schemas.enums import EventType, JobStatus

class LogPayload(BaseModel):
    level: str
    message: str
    logger: Optional[str] = None

class ProgressPayload(BaseModel):
    percentage: float = Field(..., ge=0.0, le=100.0)
    message: Optional[str] = None
    eta_seconds: Optional[float] = None

class MetricPayload(BaseModel):
    step: int
    metrics: Dict[str, float]
    epoch: Optional[int] = None

class ArtifactPayload(BaseModel):
    name: str
    path: str
    type: str
    size_bytes: Optional[int] = None

class StatusPayload(BaseModel):
    previous_status: JobStatus
    current_status: JobStatus
    message: Optional[str] = None

class EventEnvelope(BaseModel):
    job_id: str
    seq: int = Field(..., ge=1)
    ts: int
    type: EventType
    payload: Dict[str, Any]
