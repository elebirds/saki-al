"""
L3 Job schemas for runtime execution APIs.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict

from saki_api.models.enums import (
    TrainingJobStatus,
    ALLoopStatus,
    ALLoopMode,
    LoopRoundStatus,
    AnnotationBatchStatus,
)


class LoopSimulationConfig(BaseModel):
    oracle_commit_id: Optional[uuid.UUID] = None
    initial_seed_count: int = Field(default=100, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    max_rounds: int = Field(default=5, ge=1)
    split_seed: int = Field(default=0, ge=0)
    random_seed: int = Field(default=0, ge=0)
    require_fully_labeled: bool = True


class LoopCreateRequest(BaseModel):
    name: str
    branch_id: uuid.UUID
    mode: ALLoopMode = ALLoopMode.ACTIVE_LEARNING
    query_strategy: str
    model_arch: str
    global_config: Dict[str, Any] = Field(default_factory=dict)
    model_request_config: Dict[str, Any] = Field(default_factory=dict)
    simulation_config: LoopSimulationConfig = Field(default_factory=LoopSimulationConfig)
    experiment_group_id: Optional[uuid.UUID] = None
    status: ALLoopStatus = ALLoopStatus.DRAFT
    max_rounds: int = Field(default=5, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = True


class LoopUpdateRequest(BaseModel):
    name: Optional[str] = None
    mode: Optional[ALLoopMode] = None
    query_strategy: Optional[str] = None
    model_arch: Optional[str] = None
    global_config: Optional[Dict[str, Any]] = None
    model_request_config: Optional[Dict[str, Any]] = None
    simulation_config: Optional[LoopSimulationConfig] = None
    experiment_group_id: Optional[uuid.UUID] = None
    max_rounds: Optional[int] = Field(default=None, ge=1)
    query_batch_size: Optional[int] = Field(default=None, ge=1)
    min_seed_labeled: Optional[int] = Field(default=None, ge=1)
    min_new_labels_per_round: Optional[int] = Field(default=None, ge=1)
    stop_patience_rounds: Optional[int] = Field(default=None, ge=1)
    stop_min_gain: Optional[float] = None
    auto_register_model: Optional[bool] = None


LoopRecoverMode = Literal["retry_same_params", "rerun_with_overrides"]


class LoopRecoverOverrides(BaseModel):
    query_strategy: Optional[str] = None
    plugin_id: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    resources: Optional[Dict[str, Any]] = None


class LoopRecoverRequest(BaseModel):
    mode: LoopRecoverMode = "retry_same_params"
    overrides: Optional[LoopRecoverOverrides] = None


class LoopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: ALLoopMode
    query_strategy: str
    model_arch: str
    global_config: Dict[str, Any]
    model_request_config: Dict[str, Any] = Field(default_factory=dict)
    simulation_config: LoopSimulationConfig = Field(default_factory=LoopSimulationConfig)
    experiment_group_id: Optional[uuid.UUID] = None
    current_iteration: int
    status: ALLoopStatus
    max_rounds: int
    query_batch_size: int
    min_seed_labeled: int
    min_new_labels_per_round: int
    stop_patience_rounds: int
    stop_min_gain: float
    auto_register_model: bool
    last_job_id: Optional[uuid.UUID] = None
    latest_model_id: Optional[uuid.UUID] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobCreateRequest(BaseModel):
    project_id: uuid.UUID
    source_commit_id: uuid.UUID
    plugin_id: str
    job_type: str = "train_detection"
    mode: ALLoopMode = ALLoopMode.ACTIVE_LEARNING
    query_strategy: str
    params: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    strategy_params: Dict[str, Any] = Field(default_factory=dict)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: uuid.UUID
    status: TrainingJobStatus
    job_type: str
    plugin_id: str
    mode: ALLoopMode
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
    round_index: int
    strategy_params: Dict[str, Any]
    model_id: Optional[uuid.UUID] = None
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


class JobArtifactDownloadResponse(BaseModel):
    job_id: uuid.UUID
    artifact_name: str
    download_url: str
    expires_in_hours: int = Field(default=2, ge=1, le=24)


class LoopRoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    loop_id: uuid.UUID
    round_index: int
    source_commit_id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    annotation_batch_id: Optional[uuid.UUID] = None
    status: LoopRoundStatus
    metrics: Dict[str, Any]
    selected_count: int
    labeled_count: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AnnotationBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: uuid.UUID
    job_id: uuid.UUID
    round_index: int
    status: AnnotationBatchStatus
    total_count: int
    annotated_count: int
    closed_at: Optional[datetime] = None
    meta: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnnotationBatchItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    sample_id: uuid.UUID
    rank: int
    score: float
    reason: Dict[str, Any]
    prediction_snapshot: Dict[str, Any]
    is_annotated: bool
    annotated_at: Optional[datetime] = None
    annotation_commit_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class AnnotationBatchCreateRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=5000)


class LoopSummaryRead(BaseModel):
    loop_id: uuid.UUID
    status: ALLoopStatus
    rounds_total: int
    rounds_completed: int
    selected_total: int
    labeled_total: int
    metrics_latest: Dict[str, Any]


class SimulationExperimentCreateRequest(BaseModel):
    branch_id: uuid.UUID
    experiment_name: Optional[str] = None
    model_arch: str
    strategies: List[str]
    global_config: Dict[str, Any] = Field(default_factory=dict)
    model_request_config: Dict[str, Any] = Field(default_factory=dict)
    simulation_config: LoopSimulationConfig
    status: ALLoopStatus = ALLoopStatus.DRAFT


class SimulationExperimentCreateResponse(BaseModel):
    experiment_group_id: uuid.UUID
    loops: List[LoopRead]


class SimulationCurvePointRead(BaseModel):
    round_index: int
    labeled_count: int
    map50: float
    recall: float


class SimulationLoopCurveRead(BaseModel):
    loop_id: uuid.UUID
    loop_name: str
    query_strategy: str
    points: List[SimulationCurvePointRead]


class SimulationExperimentCurvesRead(BaseModel):
    experiment_group_id: uuid.UUID
    loops: List[SimulationLoopCurveRead]
