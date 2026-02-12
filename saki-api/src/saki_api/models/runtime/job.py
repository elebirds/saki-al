"""Job model for loop-level aggregation."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, Relationship, SQLModel

from saki_api.models.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.models.enums import ALLoopMode, JobStatusV2

if TYPE_CHECKING:
    from saki_api.models.project.project import Project
    from saki_api.models.runtime.job_task import JobTask
    from saki_api.models.runtime.loop import ALLoop
    from saki_api.models.runtime.model import Model


class JobBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    round_index: int = Field(index=True)
    mode: ALLoopMode = Field(default=ALLoopMode.ACTIVE_LEARNING)

    summary_status: JobStatusV2 = Field(default=JobStatusV2.JOB_PENDING, index=True)
    task_counts: Dict[str, int] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    job_type: str = Field(default="loop_job", index=True)
    plugin_id: str = Field(default="", index=True)
    query_strategy: str = Field(default="random")
    params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    source_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")
    result_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")

    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    retry_count: int = Field(default=0)
    last_error: Optional[str] = Field(default=None, max_length=4000)

    final_metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    final_artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    strategy_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    model_id: Optional[uuid.UUID] = Field(default=None, foreign_key="model.id", index=True)


class Job(JobBase, TimestampMixin, UUIDMixin, table=True):
    __tablename__ = "job"

    project: "Project" = Relationship(back_populates="jobs")
    loop: "ALLoop" = Relationship(
        back_populates="jobs",
        sa_relationship_kwargs={"foreign_keys": "[Job.loop_id]"},
    )
    model: Optional["Model"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Job.model_id]"})
    tasks: List["JobTask"] = Relationship(back_populates="job")
