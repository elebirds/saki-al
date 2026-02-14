"""DTOs for runtime task event/result persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from saki_api.modules.shared.modeling.enums import StepStatus


class RuntimeArtifactDTO(BaseModel):
    name: str
    kind: str = "artifact"
    uri: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class RuntimeTaskCandidateDTO(BaseModel):
    sample_id: uuid.UUID
    rank: int
    score: float
    reason: dict[str, Any] = Field(default_factory=dict)


class RuntimeTaskEventDTO(BaseModel):
    task_id: uuid.UUID
    seq: int
    ts: datetime
    event_type: Literal["status", "log", "progress", "metric", "artifact"]
    payload: dict[str, Any] = Field(default_factory=dict)
    status: StepStatus | None = None
    request_id: str | None = None


class RuntimeTaskResultDTO(BaseModel):
    task_id: uuid.UUID
    status: StepStatus
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts: list[RuntimeArtifactDTO] = Field(default_factory=list)
    candidates: list[RuntimeTaskCandidateDTO] = Field(default_factory=list)
    last_error: str | None = None

