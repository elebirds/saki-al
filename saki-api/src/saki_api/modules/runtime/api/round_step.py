"""L3 runtime schemas for Loop/Round/Step architecture."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field

from saki_api.modules.shared.modeling.enums import (
    LoopActionKey,
    LoopMode,
    LoopGate,
    LoopLifecycle,
    RoundSelectionOverrideOp,
    RoundStatus,
    SnapshotUpdateMode,
    SnapshotValPolicy,
    StepDispatchKind,
    StepStatus,
    StepType,
    LoopPhase,
)
from saki_api.modules.storage.api.sample import ProjectSampleRead


class LoopSimulationConfig(BaseModel):
    oracle_commit_id: Optional[uuid.UUID] = None
    seed_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    step_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    max_rounds: int = Field(default=20, ge=1)


class LoopCreateRequest(BaseModel):
    name: str
    branch_id: uuid.UUID
    mode: LoopMode = LoopMode.ACTIVE_LEARNING
    model_arch: str
    config: Dict[str, Any] = Field(default_factory=dict)
    lifecycle: LoopLifecycle = LoopLifecycle.DRAFT


class LoopUpdateRequest(BaseModel):
    name: Optional[str] = None
    mode: Optional[LoopMode] = None
    model_arch: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    lifecycle: Optional[LoopLifecycle] = None


class LoopCreateData(BaseModel):
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: LoopMode = LoopMode.ACTIVE_LEARNING
    phase: LoopPhase = LoopPhase.AL_BOOTSTRAP
    phase_meta: Dict[str, Any] = Field(default_factory=dict)
    model_arch: str
    config: Dict[str, Any] = Field(default_factory=dict)
    current_iteration: int = Field(default=0, ge=0)
    lifecycle: LoopLifecycle = LoopLifecycle.DRAFT
    max_rounds: int = Field(default=20, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = True
    active_snapshot_version_id: Optional[uuid.UUID] = None
    terminal_reason: Optional[str] = None


class LoopPatch(BaseModel):
    name: Optional[str] = None
    mode: Optional[LoopMode] = None
    phase: Optional[LoopPhase] = None
    phase_meta: Optional[Dict[str, Any]] = None
    model_arch: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    current_iteration: Optional[int] = Field(default=None, ge=0)
    lifecycle: Optional[LoopLifecycle] = None
    max_rounds: Optional[int] = Field(default=None, ge=1)
    query_batch_size: Optional[int] = Field(default=None, ge=1)
    min_seed_labeled: Optional[int] = Field(default=None, ge=1)
    min_new_labels_per_round: Optional[int] = Field(default=None, ge=1)
    stop_patience_rounds: Optional[int] = Field(default=None, ge=1)
    stop_min_gain: Optional[float] = None
    auto_register_model: Optional[bool] = None
    active_snapshot_version_id: Optional[uuid.UUID] = None
    terminal_reason: Optional[str] = None


class LoopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    mode: LoopMode
    phase: LoopPhase
    gate: LoopGate
    phase_meta: Dict[str, Any]
    gate_meta: Dict[str, Any]
    model_arch: str
    config: Dict[str, Any]
    active_snapshot_version_id: Optional[uuid.UUID] = None
    current_iteration: int
    lifecycle: LoopLifecycle
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
    attempt_index: int
    mode: LoopMode
    state: RoundStatus
    awaiting_confirm: bool = False
    step_counts: Dict[str, int]
    round_type: str
    plugin_id: str
    input_commit_id: Optional[uuid.UUID] = None
    output_commit_id: Optional[uuid.UUID] = None
    retry_of_round_id: Optional[uuid.UUID] = None
    retry_reason: Optional[str] = None
    assigned_executor_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    retry_count: int
    terminal_reason: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    confirmed_commit_id: Optional[uuid.UUID] = None
    confirmed_revealed_count: int = 0
    confirmed_selected_count: int = 0
    confirmed_effective_min_required: int = 0
    final_metrics: Dict[str, Any]
    train_final_metrics: Dict[str, Any] = Field(default_factory=dict)
    eval_final_metrics: Dict[str, Any] = Field(default_factory=dict)
    final_metrics_source: Literal["eval", "train", "other", "none"] = "none"
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
    level: Optional[str] = None
    status: Optional[str] = None
    kind: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    message_key: Optional[str] = None
    message_params: Dict[str, Any] = Field(default_factory=dict)
    message_text: str = ""
    raw_message: str = ""
    source: Optional[str] = None
    group_id: Optional[str] = None
    line_count: int = 1


class StepEventFacetsRead(BaseModel):
    event_types: Dict[str, int] = Field(default_factory=dict)
    levels: Dict[str, int] = Field(default_factory=dict)
    tags: Dict[str, int] = Field(default_factory=dict)


class StepEventQueryResponse(BaseModel):
    items: List[StepEventRead] = Field(default_factory=list)
    next_after_seq: Optional[int] = None
    facets: Optional[StepEventFacetsRead] = None


class RoundEventRead(BaseModel):
    step_id: uuid.UUID
    step_index: int
    step_type: StepType
    stage: str
    seq: int
    ts: datetime
    event_type: str
    payload: Dict[str, Any]
    level: Optional[str] = None
    status: Optional[str] = None
    kind: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    message_key: Optional[str] = None
    message_params: Dict[str, Any] = Field(default_factory=dict)
    message_text: str = ""
    raw_message: str = ""
    source: Optional[str] = None
    group_id: Optional[str] = None
    line_count: int = 1


class RoundEventQueryResponse(BaseModel):
    items: List[RoundEventRead] = Field(default_factory=list)
    next_after_cursor: Optional[str] = None
    has_more: bool = False


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


class RoundSelectionOverrideRead(BaseModel):
    sample_id: uuid.UUID
    op: RoundSelectionOverrideOp
    reason: Optional[str] = None


class RoundSelectionRead(BaseModel):
    round_id: uuid.UUID
    loop_id: uuid.UUID
    round_index: int
    attempt_index: int
    topk: int
    review_pool_size: int
    auto_selected: List[StepCandidateRead] = Field(default_factory=list)
    score_pool: List[StepCandidateRead] = Field(default_factory=list)
    overrides: List[RoundSelectionOverrideRead] = Field(default_factory=list)
    effective_selected: List[StepCandidateRead] = Field(default_factory=list)
    selected_count: int = 0
    include_count: int = 0
    exclude_count: int = 0


class RoundSelectionApplyRequest(BaseModel):
    include_sample_ids: List[uuid.UUID] = Field(default_factory=list)
    exclude_sample_ids: List[uuid.UUID] = Field(default_factory=list)
    reason: Optional[str] = None


class RoundSelectionApplyResponse(BaseModel):
    round_id: uuid.UUID
    selected_count: int
    include_count: int
    exclude_count: int
    effective_selected: List[StepCandidateRead] = Field(default_factory=list)


class StepArtifactRead(BaseModel):
    name: str
    kind: str
    uri: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class StepArtifactsResponse(BaseModel):
    step_id: uuid.UUID
    artifacts: List[StepArtifactRead]


class RoundArtifactRead(BaseModel):
    step_id: uuid.UUID
    step_index: int
    stage: str
    artifact_class: str
    name: str
    kind: str
    uri: str
    size: Optional[int] = None
    created_at: Optional[datetime] = None


class RoundArtifactsResponse(BaseModel):
    round_id: uuid.UUID
    items: List[RoundArtifactRead] = Field(default_factory=list)


class RoundMissingSamplesDatasetStatRead(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str = ""
    count: int = 0


class RoundMissingSamplesResponse(BaseModel):
    loop_id: uuid.UUID
    round_id: uuid.UUID
    round_index: int
    selected_count: int = 0
    revealed_count: int = 0
    missing_count: int = 0
    min_required: int = 0
    configured_min_required: int = 0
    dataset_stats: List[RoundMissingSamplesDatasetStatRead] = Field(default_factory=list)
    items: List[ProjectSampleRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0
    size: int = 0
    has_more: bool = False


class PredictionModelSource(BaseModel):
    kind: Literal["model"] = "model"
    model_id: uuid.UUID
    artifact_name: str = "best.pt"


class PredictionSetGenerateRequest(BaseModel):
    plugin_id: str
    target_round_id: uuid.UUID
    model_source: PredictionModelSource
    target_branch_id: uuid.UUID
    base_commit_id: uuid.UUID
    predict_conf: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    scope_type: str = "sample_status"
    scope_payload: Dict[str, Any] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)


class PredictionSetRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    loop_id: Optional[uuid.UUID] = None
    plugin_id: str
    source_round_id: Optional[uuid.UUID] = None
    source_step_id: Optional[uuid.UUID] = None
    model_id: uuid.UUID
    base_commit_id: Optional[uuid.UUID] = None
    scope_type: str
    scope_payload: Dict[str, Any] = Field(default_factory=dict)
    status: str
    total_items: int = 0
    params: Dict[str, Any] = Field(default_factory=dict)
    last_error: Optional[str] = None
    task_step_id: Optional[uuid.UUID] = None
    task_step_state: Optional[StepStatus] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class PredictionTaskRead(PredictionSetRead):
    pass


class PredictionItemRead(BaseModel):
    sample_id: uuid.UUID
    rank: int
    score: float
    label_id: Optional[uuid.UUID] = None
    geometry: Dict[str, Any] = Field(default_factory=dict)
    attrs: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    meta: Dict[str, Any] = Field(default_factory=dict)


class PredictionSetDetailRead(BaseModel):
    prediction_set: PredictionSetRead
    items: List[PredictionItemRead] = Field(default_factory=list)


class PredictionSetApplyRequest(BaseModel):
    branch_name: Optional[str] = None
    dry_run: bool = False


class PredictionSetApplyResponse(BaseModel):
    prediction_set_id: uuid.UUID
    applied_count: int = 0
    status: str


class StepArtifactDownloadResponse(BaseModel):
    step_id: uuid.UUID
    artifact_name: str
    download_url: str
    expires_in_hours: int = Field(default=2, ge=1, le=24)


class LoopSummaryRead(BaseModel):
    loop_id: uuid.UUID
    lifecycle: LoopLifecycle
    phase: LoopPhase
    rounds_total: int
    attempts_total: int
    rounds_succeeded: int
    steps_total: int
    steps_succeeded: int
    metrics_latest: Dict[str, Any]
    metrics_latest_train: Dict[str, Any] = Field(default_factory=dict)
    metrics_latest_eval: Dict[str, Any] = Field(default_factory=dict)
    metrics_latest_source: Literal["eval", "train", "other", "none"] = "none"


class LoopActionSpec(BaseModel):
    key: LoopActionKey | str
    label: str
    runnable: bool = True
    requires_confirm: bool = False
    payload: Dict[str, Any] = Field(default_factory=dict)


class SnapshotInitRequest(BaseModel):
    seed: Optional[str] = None
    train_seed_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    val_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    test_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    val_policy: SnapshotValPolicy = SnapshotValPolicy.ANCHOR_ONLY
    sample_ids: Optional[List[uuid.UUID]] = None


class SnapshotUpdateRequest(BaseModel):
    mode: SnapshotUpdateMode = SnapshotUpdateMode.APPEND_ALL_TO_POOL
    seed: Optional[str] = None
    sample_ids: Optional[List[uuid.UUID]] = None
    batch_test_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    batch_val_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    val_policy: Optional[SnapshotValPolicy] = None


class SnapshotVersionRead(BaseModel):
    id: uuid.UUID
    loop_id: uuid.UUID
    version_index: int
    parent_version_id: Optional[uuid.UUID] = None
    update_mode: SnapshotUpdateMode
    val_policy: SnapshotValPolicy
    seed: str
    rule_json: Dict[str, Any]
    manifest_hash: str
    sample_count: int
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class SnapshotVersionSummaryRead(BaseModel):
    id: uuid.UUID
    version_index: int
    update_mode: SnapshotUpdateMode
    val_policy: SnapshotValPolicy
    sample_count: int
    manifest_hash: str
    created_at: datetime


class LoopSnapshotRead(BaseModel):
    loop_id: uuid.UUID
    active_snapshot_version_id: Optional[uuid.UUID] = None
    active: Optional[SnapshotVersionRead] = None
    history: List[SnapshotVersionSummaryRead] = Field(default_factory=list)
    primary_view: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    advanced_view: Dict[str, Any] = Field(default_factory=dict)


class SnapshotMutationResponse(BaseModel):
    loop_id: uuid.UUID
    gate: LoopGate
    active_snapshot_version_id: uuid.UUID
    version_index: int
    created: bool = True
    sample_count: int = 0


class LoopGateResponse(BaseModel):
    loop_id: uuid.UUID
    gate: LoopGate
    gate_meta: Dict[str, Any] = Field(default_factory=dict)
    primary_action: Optional[LoopActionSpec] = None
    actions: List[LoopActionSpec] = Field(default_factory=list)
    decision_token: str = ""
    blocking_reasons: List[str] = Field(default_factory=list)


class LoopActionRequest(BaseModel):
    action: Optional[LoopActionKey] = None
    force: bool = False
    decision_token: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LoopActionResponse(BaseModel):
    loop_id: uuid.UUID
    executed_action: Optional[LoopActionKey] = None
    command_id: Optional[str] = None
    message: str = ""
    gate: LoopGate
    gate_meta: Dict[str, Any] = Field(default_factory=dict)
    primary_action: Optional[LoopActionSpec] = None
    actions: List[LoopActionSpec] = Field(default_factory=list)
    decision_token: str = ""
    blocking_reasons: List[str] = Field(default_factory=list)
    phase: LoopPhase
    lifecycle: LoopLifecycle


class RoundPredictionCleanupResponse(BaseModel):
    loop_id: uuid.UUID
    round_index: int
    score_steps: int
    candidate_rows_deleted: int
    event_rows_deleted: int
    metric_rows_deleted: int
