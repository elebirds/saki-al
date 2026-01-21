import uuid
from typing import Dict, Any, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Column, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON

if TYPE_CHECKING:
    from saki_api.models.l2.branch import Branch
    from saki_api.models.l2.project import Project
    from saki_api.models.l3.job import Job


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

    # 关系
    project: "Project" = Relationship(back_populates="loops")
    branch: "Branch" = Relationship(back_populates="active_learning_loop")
    training_jobs: List["Job"] = Relationship(back_populates="loop")
