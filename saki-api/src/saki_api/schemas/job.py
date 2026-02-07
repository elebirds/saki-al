from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel

from saki_api.models.enums import TrainingJobStatus


class JobCreateRequest(BaseModel):
    project_id: UUID
    source_commit_id: UUID
    plugin_id: str
    job_type: str = "train_detection"
    params: Dict[str, Any]
    resources: Dict[str, Any]


class JobRead(BaseModel):
    id: UUID
    project_id: UUID
    loop_id: UUID
    iteration: int
    status: TrainingJobStatus
    job_type: str
    plugin_id: str
    source_commit_id: UUID
    result_commit_id: Optional[UUID] = None
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    params: Dict[str, Any]
    resources: Dict[str, Any]


class JobCommandResponse(BaseModel):
    request_id: str
    job_id: UUID
    status: str
