"""L3 runtime schemas for Loop/Job/Task architecture."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from saki_api.modules.shared.modeling.enums import (
    ALLoopMode,
    ALLoopStatus,
    JobStatusV2,
    JobTaskStatus,
    JobTaskType,
    LoopPhase,
)


class LoopSimulationConfig(BaseModel):
    oracle_commit_id: Optional[uuid.UUID] = None
    seed_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    step_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    max_rounds: int = Field(default=20, ge=1)
    random_baseline_enabled: bool = True
    seeds: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    single_seed: Optional[int] = None


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
    max_rounds: int = Field(default=20, ge=1)
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


class LoopCreateData(BaseModel):
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: ALLoopMode = ALLoopMode.ACTIVE_LEARNING
    phase: LoopPhase = LoopPhase.AL_BOOTSTRAP
    phase_meta: Dict[str, Any] = Field(default_factory=dict)
    query_strategy: str
    model_arch: str
    experiment_group_id: Optional[uuid.UUID] = None
    global_config: Dict[str, Any] = Field(default_factory=dict)
    current_iteration: int = Field(default=0, ge=0)
    status: ALLoopStatus = ALLoopStatus.DRAFT
    max_rounds: int = Field(default=20, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = True
    last_job_id: Optional[uuid.UUID] = None
    latest_model_id: Optional[uuid.UUID] = None
    last_error: Optional[str] = None


class LoopPatch(BaseModel):
    name: Optional[str] = None
    mode: Optional[ALLoopMode] = None
    phase: Optional[LoopPhase] = None
    phase_meta: Optional[Dict[str, Any]] = None
    query_strategy: Optional[str] = None
    model_arch: Optional[str] = None
    experiment_group_id: Optional[uuid.UUID] = None
    global_config: Optional[Dict[str, Any]] = None
    current_iteration: Optional[int] = Field(default=None, ge=0)
    status: Optional[ALLoopStatus] = None
    max_rounds: Optional[int] = Field(default=None, ge=1)
    query_batch_size: Optional[int] = Field(default=None, ge=1)
    min_seed_labeled: Optional[int] = Field(default=None, ge=1)
    min_new_labels_per_round: Optional[int] = Field(default=None, ge=1)
    stop_patience_rounds: Optional[int] = Field(default=None, ge=1)
    stop_min_gain: Optional[float] = None
    auto_register_model: Optional[bool] = None
    last_job_id: Optional[uuid.UUID] = None
    latest_model_id: Optional[uuid.UUID] = None
    last_error: Optional[str] = None


class LoopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: ALLoopMode
    phase: LoopPhase
    phase_meta: Dict[str, Any]
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
    source_commit_id: Optional[uuid.UUID] = None
    plugin_id: str
    job_type: str = "loop_job"
    mode: ALLoopMode = ALLoopMode.ACTIVE_LEARNING
    query_strategy: str
    params: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    strategy_params: Dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
    project_id: uuid.UUID
    loop_id: uuid.UUID
    round_index: int = Field(ge=1)
    mode: ALLoopMode = ALLoopMode.ACTIVE_LEARNING
    summary_status: JobStatusV2 = JobStatusV2.JOB_PENDING
    task_counts: Dict[str, int] = Field(default_factory=dict)
    job_type: str = "loop_job"
    plugin_id: str
    query_strategy: str
    params: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    source_commit_id: Optional[uuid.UUID] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    last_error: Optional[str] = None
    final_metrics: Dict[str, Any] = Field(default_factory=dict)
    final_artifacts: Dict[str, Any] = Field(default_factory=dict)
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    model_id: Optional[uuid.UUID] = None


class JobUpdate(BaseModel):
    summary_status: Optional[JobStatusV2] = None
    task_counts: Optional[Dict[str, int]] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    retry_count: Optional[int] = Field(default=None, ge=0)
    last_error: Optional[str] = None
    final_metrics: Optional[Dict[str, Any]] = None
    final_artifacts: Optional[Dict[str, Any]] = None
    strategy_params: Optional[Dict[str, Any]] = None
    model_id: Optional[uuid.UUID] = None


class JobTaskCreate(BaseModel):
    job_id: uuid.UUID
    task_type: JobTaskType
    status: JobTaskStatus = JobTaskStatus.PENDING
    round_index: int = Field(default=1, ge=1)
    task_index: int = Field(default=1, ge=1)
    depends_on: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    source_commit_id: Optional[uuid.UUID] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    last_error: Optional[str] = None


class JobTaskUpdate(BaseModel):
    status: Optional[JobTaskStatus] = None
    metrics: Optional[Dict[str, Any]] = None
    artifacts: Optional[Dict[str, Any]] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    attempt: Optional[int] = Field(default=None, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    last_error: Optional[str] = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: uuid.UUID
    round_index: int
    mode: ALLoopMode
    summary_status: JobStatusV2
    task_counts: Dict[str, int]
    job_type: str
    plugin_id: str
    query_strategy: str
    source_commit_id: Optional[uuid.UUID] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    retry_count: int
    last_error: Optional[str] = None
    final_metrics: Dict[str, Any]
    final_artifacts: Dict[str, Any]
    params: Dict[str, Any]
    resources: Dict[str, Any]
    strategy_params: Dict[str, Any]
    model_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class JobCommandResponse(BaseModel):
    request_id: str
    job_id: uuid.UUID
    status: str


class JobTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    task_type: JobTaskType
    status: JobTaskStatus
    round_index: int
    task_index: int
    depends_on: List[str]
    params: Dict[str, Any]
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    source_commit_id: Optional[uuid.UUID] = None
    result_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    attempt: int
    max_attempts: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskCommandResponse(BaseModel):
    request_id: str
    task_id: uuid.UUID
    status: str


class TaskEventRead(BaseModel):
    seq: int
    ts: datetime
    event_type: str
    payload: Dict[str, Any]


class TaskMetricPointRead(BaseModel):
    step: int
    epoch: Optional[int]
    metric_name: str
    metric_value: float
    ts: datetime


class TaskCandidateRead(BaseModel):
    sample_id: uuid.UUID
    rank: int
    score: float
    reason: Dict[str, Any]
    prediction_snapshot: Dict[str, Any]


class TaskArtifactRead(BaseModel):
    name: str
    kind: str
    uri: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class TaskArtifactsResponse(BaseModel):
    task_id: uuid.UUID
    artifacts: List[TaskArtifactRead]


class TaskArtifactDownloadResponse(BaseModel):
    task_id: uuid.UUID
    artifact_name: str
    download_url: str
    expires_in_hours: int = Field(default=2, ge=1, le=24)


class LoopSummaryRead(BaseModel):
    loop_id: uuid.UUID
    status: ALLoopStatus
    phase: LoopPhase
    jobs_total: int
    jobs_succeeded: int
    tasks_total: int
    tasks_succeeded: int
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
    strategy: str
    round_index: int
    target_ratio: float
    mean_metric: float
    std_metric: float


class SimulationStrategySummaryRead(BaseModel):
    strategy: str
    seeds: List[int]
    final_mean: float
    final_std: float
    aulc_mean: float


class SimulationComparisonRead(BaseModel):
    experiment_group_id: uuid.UUID
    metric_name: str
    curves: List[SimulationCurvePointRead]
    strategies: List[SimulationStrategySummaryRead]
    baseline_strategy: str
    delta_vs_baseline: Dict[str, float]


class LoopConfirmResponse(BaseModel):
    loop_id: uuid.UUID
    phase: LoopPhase
    status: ALLoopStatus


class RoundPredictionCleanupResponse(BaseModel):
    loop_id: uuid.UUID
    round_index: int
    score_steps: int
    candidate_rows_deleted: int
    event_rows_deleted: int
    metric_rows_deleted: int
