import uuid
from typing import List, Dict, Any, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import TaskType, ProjectStatus

if TYPE_CHECKING:
    from saki_api.models.l1.dataset import Dataset
    from saki_api.models.l3.job import Job
    from saki_api.models.l3.loop import ALLoop
    from saki_api.models.l2.branch import Branch
    from saki_api.models.l2.commit import Commit
    from saki_api.models.l2.label import Label


class ProjectDataset(SQLModel, table=True):
    """
    Base model for the link between Project and Dataset.
    """
    __tablename__ = "project_dataset"
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True, description="ID of the project.")
    dataset_id: uuid.UUID = Field(foreign_key="dataset.id", primary_key=True, description="ID of the dataset.")

    project: "Project" = Relationship(back_populates="dataset_links")
    dataset: "Dataset" = Relationship(back_populates="project_links")


class ProjectBase(SQLModel):
    """
    Project 是主动学习和版本控制的核心容器（Repository）。
    """
    # 基础字段
    name: str = Field(index=True, description="Name of the project.")
    description: str | None = Field(default=None, description="Description of the project.")
    # Task type - determines ML model type (classification, detection, etc.)
    task_type: TaskType = Field(default=TaskType.DETECTION, description="Type of ML task for active learning.")
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE, description="Current status of the project.")

    # 配置字段
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON),
                                   description="Configuration of the project.")


class Project(ProjectBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Project.
    Used for active learning training, can link to multiple Datasets.
    Integrates with Git-like version control for annotation management.
    """
    __tablename__ = "project"

    # 1. 数据关联 (L1)
    dataset_links: List["ProjectDataset"] = Relationship(back_populates="project")

    # 2. 版本控制 (L2)
    branches: List["Branch"] = Relationship(back_populates="project", cascade_delete=True)
    commits: List["Commit"] = Relationship(back_populates="project", cascade_delete=True)
    labels: List["Label"] = Relationship(back_populates="project", cascade_delete=True)

    # 3. 训练任务 (L3)
    jobs: List["Job"] = Relationship(back_populates="project")
    loops: List["ALLoop"] = Relationship(back_populates="project", cascade_delete=True)
