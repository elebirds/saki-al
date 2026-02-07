import uuid
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Column, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON
from saki_api.models.enums import ALLoopStatus

if TYPE_CHECKING:
    from saki_api.models.l2.branch import Branch
    from saki_api.models.l2.project import Project
    from saki_api.models.l3.job import Job
    from saki_api.models.l3.loop_round import LoopRound
    from saki_api.models.l3.annotation_batch import AnnotationBatch
    from saki_api.models.l3.model import Model


class ALLoop(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """
    L3 实验层：主动学习闭环。
    代表一个独立的实验路径，如“基于不确定性采样的 YOLOv8 实验”。
    """
    __tablename__ = "loop"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    branch_id: uuid.UUID = Field(foreign_key="branch.id", unique=True)

    name: str = Field(max_length=100, description="实验名称")

    # 实验策略配置
    query_strategy: str = Field(description="采样策略 (Random, LeastConfidence, etc.)")
    model_arch: str = Field(description="模型架构 (yolov8_obb, rt_detr, etc.)")

    # 全局超参数设置
    global_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="实验线通用的超参数配置"
    )

    # 状态与统计
    current_iteration: int = Field(default=0, description="当前迭代轮次")
    is_active: bool = Field(default=True)
    status: ALLoopStatus = Field(default=ALLoopStatus.DRAFT, index=True)
    max_rounds: int = Field(default=5, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = Field(default=True)
    last_job_id: Optional[uuid.UUID] = Field(default=None, foreign_key="job.id", index=True)
    latest_model_id: Optional[uuid.UUID] = Field(default=None, foreign_key="model.id", index=True)
    last_error: str | None = Field(default=None, max_length=4000)

    # 关系
    project: "Project" = Relationship(back_populates="loops")
    branch: "Branch" = Relationship(back_populates="active_learning_loop")
    jobs: List["Job"] = Relationship(
        back_populates="loop",
        sa_relationship_kwargs={"foreign_keys": "[Job.loop_id]"},
    )
    rounds: List["LoopRound"] = Relationship(back_populates="loop")
    annotation_batches: List["AnnotationBatch"] = Relationship(back_populates="loop")
    latest_model: Optional["Model"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ALLoop.latest_model_id]"}
    )
