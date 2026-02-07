"""
L3 Job schemas for runtime execution APIs.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from saki_api.models.enums import TrainingJobStatus


class LoopCreateRequest(BaseModel):
    name: str
    branch_id: uuid.UUID
    query_strategy: str = "uncertainty_1_minus_max_conf"
    model_arch: str = "demo_det_v1"
    global_config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class LoopRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    query_strategy: str
    model_arch: str
    global_config: Dict[str, Any]
    current_iteration: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class JobCreateRequest(BaseModel):
    project_id: uuid.UUID
    source_commit_id: uuid.UUID
    plugin_id: str
    job_type: str = "train_detection"
    mode: str = "active_learning"
    query_strategy: str = "uncertainty_1_minus_max_conf"
    params: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)


class JobRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: uuid.UUID
    iteration: int
    status: TrainingJobStatus
    job_type: str
    plugin_id: str
    mode: str
    query_strategy: str
    source_commit_id: uuid.UUID
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    retry_count: int
    last_error: Optional[str] = None
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    params: Dict[str, Any]
    resources: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class JobCommandResponse(BaseModel):
    request_id: str
    job_id: uuid.UUID
    status: str


class JobEventRead(BaseModel):
    seq: int
    ts: datetime
    event_type: str
    payload: Dict[str, Any]


class JobMetricPointRead(BaseModel):
    step: int
    epoch: Optional[int]
    metric_name: str
    metric_value: float
    ts: datetime


class JobCandidateRead(BaseModel):
    sample_id: uuid.UUID
    score: float
    extra: Dict[str, Any]
    prediction_snapshot: Dict[str, Any]


class JobArtifactRead(BaseModel):
    name: str
    kind: str
    uri: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class JobArtifactsResponse(BaseModel):
    job_id: uuid.UUID
    artifacts: List[JobArtifactRead]
