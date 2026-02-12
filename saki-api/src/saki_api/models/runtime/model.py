import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Dict, Any

from sqlalchemy import Column
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON

if TYPE_CHECKING:
    from saki_api.models.runtime.job import Job


class Model(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """
    L3 部署层：模型注册表。
    只有被‘选中’或‘发布’的模型才在这里记录。
    """
    __tablename__ = "model"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)

    # 溯源：这个模型是哪次训练任务产出的？
    job_id: uuid.UUID | None = Field(foreign_key="job.id")
    source_commit_id: uuid.UUID | None = Field(default=None, foreign_key="commit.id", index=True)
    parent_model_id: uuid.UUID | None = Field(default=None, foreign_key="model.id", index=True)
    plugin_id: str = Field(default="", index=True)
    model_arch: str = Field(default="", index=True)

    # 核心元数据
    name: str = Field(index=True)  # 如 "FEDO-OBB-Standard-v1"
    version_tag: str = Field(default="v1.0")

    # 存储与访问
    weights_path: str = Field(description="权重文件在 MinIO 的持久化地址")
    status: str = Field(default="candidate")  # candidate, production, archived
    metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    promoted_at: datetime | None = Field(default=None)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")

    # 关系
    job: Optional["Job"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Model.job_id]"}
    )
    parent_model: Optional["Model"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Model.parent_model_id]"}
    )
