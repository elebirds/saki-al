import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


class ModelPublishFromRoundRequest(BaseModel):
    round_id: uuid.UUID
    name: Optional[str] = None
    primary_artifact_name: Optional[str] = None
    version_tag: Optional[str] = None
    status: str = "candidate"


class ModelCreateData(BaseModel):
    project_id: uuid.UUID
    source_commit_id: Optional[uuid.UUID] = None
    source_round_id: Optional[uuid.UUID] = None
    source_task_id: Optional[uuid.UUID] = None
    parent_model_id: Optional[uuid.UUID] = None
    plugin_id: str
    model_arch: str
    name: str
    version_tag: str
    primary_artifact_name: str
    weights_path: str
    status: str = "candidate"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    publish_manifest: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[uuid.UUID] = None
    promoted_at: Optional[datetime] = None


class ModelPatch(BaseModel):
    status: Optional[str] = None
    promoted_at: Optional[datetime] = None


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_commit_id: Optional[uuid.UUID] = None
    source_round_id: Optional[uuid.UUID] = None
    source_task_id: Optional[uuid.UUID] = None
    parent_model_id: Optional[uuid.UUID] = None
    plugin_id: str
    model_arch: str
    name: str
    version_tag: str
    primary_artifact_name: str
    weights_path: str
    status: str
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    publish_manifest: Dict[str, Any]
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
