"""
Job model for experiment tracking and runtime execution.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import TrainingJobStatus

if TYPE_CHECKING:
    from saki_api.models.l3.loop import ALLoop
    from saki_api.models.l3.metric import JobSampleMetric
    from saki_api.models.l3.job_event import JobEvent
    from saki_api.models.l3.job_metric_point import JobMetricPoint
    from saki_api.models.l2.project import Project


class JobBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    iteration: int = Field(index=True, description="在该 Loop 中的迭代序号")
    status: TrainingJobStatus = Field(default=TrainingJobStatus.PENDING, index=True)

    # Runtime execution config
    job_type: str = Field(default="train_detection", index=True)
    plugin_id: str = Field(default="", index=True)
    mode: str = Field(default="active_learning", description="active_learning | simulation")
    query_strategy: str = Field(default="uncertainty_1_minus_max_conf")
    params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    # Version tracking
    source_commit_id: uuid.UUID = Field(foreign_key="commit.id", description="训练输入的快照")
    result_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", description="推理产出的快照")

    # Runtime assignment and lifecycle
    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    retry_count: int = Field(default=0)
    last_error: Optional[str] = Field(default=None, max_length=4000)

    # Aggregated outputs
    metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON), description="权重路径等")


class Job(JobBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Job.
    """
    __tablename__ = "job"

    project: "Project" = Relationship(back_populates="jobs")
    loop: "ALLoop" = Relationship(back_populates="jobs")
    sample_metrics: List["JobSampleMetric"] = Relationship(back_populates="job")
    events: List["JobEvent"] = Relationship(back_populates="job")
    metric_points: List["JobMetricPoint"] = Relationship(back_populates="job")
