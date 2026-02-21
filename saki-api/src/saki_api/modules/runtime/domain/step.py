"""Step model for runtime execution units."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import StepDispatchKind, StepStatus, StepType

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.dispatch_outbox import DispatchOutbox
    from saki_api.modules.runtime.domain.round import Round
    from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
    from saki_api.modules.runtime.domain.step_event import StepEvent
    from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint


class Step(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "step"
    __table_args__ = (UniqueConstraint("round_id", "step_index", name="uq_step_order"),)

    round_id: uuid.UUID = Field(foreign_key="round.id", index=True)
    step_type: StepType = Field(index=True)
    dispatch_kind: StepDispatchKind = Field(default=StepDispatchKind.DISPATCHABLE, index=True)
    state: StepStatus = Field(default=StepStatus.PENDING, index=True)

    round_index: int = Field(default=1, index=True)
    step_index: int = Field(default=1, index=True)

    depends_on_step_ids: List[str] = Field(default_factory=list, sa_column=Column(OPT_JSON))
    resolved_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    dataset_manifest_ref: Optional[str] = Field(default=None, max_length=512)
    snapshot_id: Optional[uuid.UUID] = Field(default=None, foreign_key="dataset_snapshot.id", index=True)
    env_overrides: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    runtime_hints: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    kernel_capability_requirements: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    gpu_exclusive: bool = Field(default=False)
    kernel_id: Optional[str] = Field(default=None, max_length=128)
    kernel_version: Optional[str] = Field(default=None, max_length=128)

    input_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", index=True)
    output_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", index=True)

    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    dispatch_request_id: Optional[str] = Field(default=None, max_length=128, index=True)
    state_version: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None, max_length=4000)

    round: "Round" = Relationship(back_populates="steps")
    events: List["StepEvent"] = Relationship(back_populates="step")
    metric_points: List["StepMetricPoint"] = Relationship(back_populates="step")
    candidates: List["StepCandidateItem"] = Relationship(back_populates="step")
    dispatch_outboxes: List["DispatchOutbox"] = Relationship(back_populates="step")
