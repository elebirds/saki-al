"""L3 runtime schemas for Loop/Round/Step architecture."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from saki_api.modules.shared.modeling.enums import (
    LoopMode,
    LoopStatus,
    RoundStatus,
    StepDispatchKind,
    StepStatus,
    StepType,
    LoopPhase,
)


class LoopSimulationConfig(BaseModel):
    oracle_commit_id: Optional[uuid.UUID] = None
    seed_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    step_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    random_baseline_enabled: bool = True
    seeds: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    single_seed: Optional[int] = None


class LoopCreateRequest(BaseModel):
    name: str
    branch_id: uuid.UUID
    mode: LoopMode = LoopMode.ACTIVE_LEARNING
    model_arch: str
    config: Dict[str, Any] = Field(default_factory=dict)
    experiment_group_id: Optional[uuid.UUID] = None
    status: LoopStatus = LoopStatus.DRAFT


class LoopUpdateRequest(BaseModel):
    name: Optional[str] = None
    mode: Optional[LoopMode] = None
    model_arch: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    experiment_group_id: Optional[uuid.UUID] = None
    status: Optional[LoopStatus] = None


class LoopCreateData(BaseModel):
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: LoopMode = LoopMode.ACTIVE_LEARNING
    phase: LoopPhase = LoopPhase.AL_BOOTSTRAP
    phase_meta: Dict[str, Any] = Field(default_factory=dict)
    model_arch: str
    experiment_group_id: Optional[uuid.UUID] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    current_iteration: int = Field(default=0, ge=0)
    status: LoopStatus = LoopStatus.DRAFT
    max_rounds: int = Field(default=20, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = True
    terminal_reason: Optional[str] = None


class LoopPatch(BaseModel):
    name: Optional[str] = None
    mode: Optional[LoopMode] = None
    phase: Optional[LoopPhase] = None
    phase_meta: Optional[Dict[str, Any]] = None
    model_arch: Optional[str] = None
    experiment_group_id: Optional[uuid.UUID] = None
    config: Optional[Dict[str, Any]] = None
    current_iteration: Optional[int] = Field(default=None, ge=0)
    status: Optional[LoopStatus] = None
    max_rounds: Optional[int] = Field(default=None, ge=1)
    query_batch_size: Optional[int] = Field(default=None, ge=1)
    min_seed_labeled: Optional[int] = Field(default=None, ge=1)
    min_new_labels_per_round: Optional[int] = Field(default=None, ge=1)
    stop_patience_rounds: Optional[int] = Field(default=None, ge=1)
    stop_min_gain: Optional[float] = None
    auto_register_model: Optional[bool] = None
    terminal_reason: Optional[str] = None


class LoopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: LoopMode
    phase: LoopPhase
    phase_meta: Dict[str, Any]
    model_arch: str
    config: Dict[str, Any]
    experiment_group_id: Optional[uuid.UUID] = None
    current_iteration: int
    status: LoopStatus
    max_rounds: int
    query_batch_size: int
    min_seed_labeled: int
    min_new_labels_per_round: int
    stop_patience_rounds: int
    stop_min_gain: float
    auto_register_model: bool
    terminal_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RoundUpdate(BaseModel):
    state: Optional[RoundStatus] = None
    step_counts: Optional[Dict[str, int]] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    output_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    retry_count: Optional[int] = Field(default=None, ge=0)
    terminal_reason: Optional[str] = None
    final_metrics: Optional[Dict[str, Any]] = None
    final_artifacts: Optional[Dict[str, Any]] = None
    strategy_params: Optional[Dict[str, Any]] = None


class RoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: uuid.UUID
    round_index: int
    mode: LoopMode
    state: RoundStatus
    step_counts: Dict[str, int]
    round_type: str
    plugin_id: str
    input_commit_id: Optional[uuid.UUID] = None
    output_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    retry_count: int
    terminal_reason: Optional[str] = None
    final_metrics: Dict[str, Any]
    final_artifacts: Dict[str, Any]
    resolved_params: Dict[str, Any]
    resources: Dict[str, Any]
    strategy_params: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RoundCommandResponse(BaseModel):
    request_id: str
    round_id: uuid.UUID
    status: str


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    round_id: uuid.UUID
    step_type: StepType
    dispatch_kind: StepDispatchKind
    state: StepStatus
    round_index: int
    step_index: int
    depends_on_step_ids: List[str]
    resolved_params: Dict[str, Any]
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    input_commit_id: Optional[uuid.UUID] = None
    output_commit_id: Optional[uuid.UUID] = None
    assigned_executor_id: Optional[str] = None
    attempt: int
    max_attempts: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class StepCommandResponse(BaseModel):
    request_id: str
    step_id: uuid.UUID
    status: str


class StepEventRead(BaseModel):
    seq: int
    ts: datetime
    event_type: str
    payload: Dict[str, Any]


class StepMetricPointRead(BaseModel):
    step: int
    epoch: Optional[int]
    metric_name: str
    metric_value: float
    ts: datetime


class StepCandidateRead(BaseModel):
    sample_id: uuid.UUID
    rank: int
    score: float
    reason: Dict[str, Any]
    prediction_snapshot: Dict[str, Any]


class StepArtifactRead(BaseModel):
    name: str
    kind: str
    uri: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class StepArtifactsResponse(BaseModel):
    step_id: uuid.UUID
    artifacts: List[StepArtifactRead]


class StepArtifactDownloadResponse(BaseModel):
    step_id: uuid.UUID
    artifact_name: str
    download_url: str
    expires_in_hours: int = Field(default=2, ge=1, le=24)


class LoopSummaryRead(BaseModel):
    loop_id: uuid.UUID
    status: LoopStatus
    phase: LoopPhase
    rounds_total: int
    rounds_succeeded: int
    steps_total: int
    steps_succeeded: int
    metrics_latest: Dict[str, Any]


class SimulationExperimentCreateRequest(BaseModel):
    branch_id: uuid.UUID
    experiment_name: Optional[str] = None
    model_arch: str
    strategies: List[str]
    config: Dict[str, Any] = Field(default_factory=dict)
    status: LoopStatus = LoopStatus.DRAFT


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
    state: LoopStatus


class RoundPredictionCleanupResponse(BaseModel):
    loop_id: uuid.UUID
    round_index: int
    score_steps: int
    candidate_rows_deleted: int
    event_rows_deleted: int
    metric_rows_deleted: int
