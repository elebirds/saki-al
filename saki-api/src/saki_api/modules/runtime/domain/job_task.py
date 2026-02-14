"""Task model for runtime execution units."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import JobTaskStatus, JobTaskType

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.job import Job
    from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
    from saki_api.modules.runtime.domain.task_event import TaskEvent
    from saki_api.modules.runtime.domain.task_metric_point import TaskMetricPoint


class JobTask(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "step"
    __table_args__ = (UniqueConstraint("job_id", "task_index", name="uq_step_order"),)

    job_id: uuid.UUID = Field(foreign_key="round.id", index=True)
    task_type: JobTaskType = Field(index=True)
    status: JobTaskStatus = Field(default=JobTaskStatus.PENDING, index=True)

    round_index: int = Field(default=1, index=True)
    task_index: int = Field(default=1, index=True)

    depends_on: List[str] = Field(default_factory=list, sa_column=Column(OPT_JSON))
    params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    source_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", index=True)
    result_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", index=True)

    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    dispatch_request_id: Optional[str] = Field(default=None, max_length=128, index=True)
    state_version: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None, max_length=4000)

    job: "Job" = Relationship(back_populates="tasks")
    events: List["TaskEvent"] = Relationship(back_populates="task")
    metric_points: List["TaskMetricPoint"] = Relationship(back_populates="task")
    candidates: List["TaskCandidateItem"] = Relationship(back_populates="task")
