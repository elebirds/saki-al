import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ModelRegisterFromJobRequest(BaseModel):
    job_id: uuid.UUID
    name: Optional[str] = None
    version_tag: str = "v1.0"
    status: str = "candidate"


class ModelRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    source_commit_id: Optional[uuid.UUID] = None
    parent_model_id: Optional[uuid.UUID] = None
    plugin_id: str
    model_arch: str
    name: str
    version_tag: str
    weights_path: str
    status: str
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    promoted_at: Optional[datetime] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class ModelPromoteRequest(BaseModel):
    status: str = Field(default="production")


class ModelArtifactDownloadResponse(BaseModel):
    model_id: uuid.UUID
    artifact_name: str
    download_url: str
    expires_in_hours: int
