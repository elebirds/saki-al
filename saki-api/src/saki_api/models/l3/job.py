"""
Job model for experiment tracking.
"""
import uuid
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import TrainingJobStatus

if TYPE_CHECKING:
    from saki_api.models.l3.loop import ALLoop
    from saki_api.models.l3.metric import JobSampleMetric
    from saki_api.models.l2.project import Project


class JobBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    iteration: int = Field(index=True, description="在该 Loop 中的迭代序号")
    status: TrainingJobStatus = Field(default=TrainingJobStatus.PENDING, index=True)

    # Runtime 相关信息
    job_type: str = Field(default="train_detection", description="Runtime job type")
    plugin_id: str = Field(default="", description="Runtime plugin id")
    params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    # 版本追踪
    source_commit_id: uuid.UUID = Field(foreign_key="commit.id", description="训练输入的快照")
    result_commit_id: Optional[uuid.UUID] = Field(foreign_key="commit.id", description="推理产出的快照")

    # 性能指标与权重
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
