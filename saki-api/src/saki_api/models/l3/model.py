import uuid
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from saki_api.models.l3.job import Job

class Model(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """
    L3 部署层：模型注册表。
    只有被‘选中’或‘发布’的模型才在这里记录。
    """
    __tablename__ = "model"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)

    # 溯源：这个模型是哪次训练任务产出的？
    job_id: uuid.UUID | None = Field(foreign_key="training_job.id")

    # 核心元数据
    name: str = Field(index=True)  # 如 "FEDO-OBB-Standard-v1"
    version_tag: str = Field(default="v1.0")

    # 存储与访问
    weights_path: str = Field(description="权重文件在 MinIO 的持久化地址")
    status: str = Field(default="candidate")  # candidate, production, archived

    # 关系
    job: Optional["Job"] = Relationship()