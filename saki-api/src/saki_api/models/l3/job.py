"""
Job model for experiment tracking and runtime execution.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import TrainingJobStatus, ALLoopMode

if TYPE_CHECKING:
    from saki_api.models.l3.loop import ALLoop
    from saki_api.models.l3.metric import JobSampleMetric
    from saki_api.models.l3.job_event import JobEvent
    from saki_api.models.l3.job_metric_point import JobMetricPoint
    from saki_api.models.l2.project import Project
    from saki_api.models.l3.loop_round import LoopRound
    from saki_api.models.l3.model import Model


class JobBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    round_index: int = Field(index=True, description="在该 Loop 中的轮次序号")
    status: TrainingJobStatus = Field(default=TrainingJobStatus.PENDING, index=True)

    # Runtime execution config
    job_type: str = Field(default="train_detection", index=True)
    plugin_id: str = Field(default="", index=True)
    mode: ALLoopMode = Field(default=ALLoopMode.ACTIVE_LEARNING, description="active_learning | simulation")
    query_strategy: str
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
    strategy_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    model_id: Optional[uuid.UUID] = Field(default=None, foreign_key="model.id", index=True)


class Job(JobBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Job.
    """
    __tablename__ = "job"

    project: "Project" = Relationship(back_populates="jobs")
    loop: "ALLoop" = Relationship(
        back_populates="jobs",
        sa_relationship_kwargs={"foreign_keys": "[Job.loop_id]"},
    )
    sample_metrics: List["JobSampleMetric"] = Relationship(back_populates="job")
    events: List["JobEvent"] = Relationship(back_populates="job")
    metric_points: List["JobMetricPoint"] = Relationship(back_populates="job")
    rounds: List["LoopRound"] = Relationship(back_populates="job")
    model: Optional["Model"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Job.model_id]"}
    )
