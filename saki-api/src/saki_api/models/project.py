from typing import List, Optional, Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import TaskType, ProjectStatus

if TYPE_CHECKING:
    from saki_api.models.system_config import QueryStrategy, BaseModel
    from saki_api.models.model_version import ModelVersion
    from saki_api.models.dataset import Dataset


class ProjectDatasetBase(SQLModel):
    """
    Base model for the link between Project and Dataset.
    """
    project_id: str = Field(foreign_key="project.id", primary_key=True, description="ID of the project.")
    dataset_id: str = Field(foreign_key="dataset.id", primary_key=True, description="ID of the dataset.")


class ProjectDataset(ProjectDatasetBase, TimestampMixin, table=True):
    """
    Link table for many-to-many relationship between Project and Dataset.
    A Project can use multiple Datasets for training.
    A Dataset can be used in multiple Projects.
    """
    __tablename__ = "project_dataset"

    # Relationship back to Project and Dataset
    project: "Project" = Relationship(back_populates="dataset_links")
    dataset: "Dataset" = Relationship(back_populates="project_links")

    # Score for samples from this dataset in this project context
    # This allows different scores for the same sample in different projects
    sample_scores: Dict[str, float] = Field(
        default={},
        sa_column=Column(JSON),
        description="Sample ID to informativeness score mapping for this project-dataset combination."
    )


class ProjectDatasetCreate(SQLModel):
    """
    Model for linking a Dataset to a Project.
    """
    dataset_id: str = Field(description="ID of the dataset to link.")


class ProjectDatasetRead(ProjectDatasetBase, TimestampMixin):
    """
    Model for reading Project-Dataset link data.
    """
    pass


class ProjectBase(SQLModel):
    """
    Base model for Project, containing common fields.
    Project is used for active learning training.
    """
    name: str = Field(index=True, description="Name of the project.")
    description: Optional[str] = Field(default=None, description="Description of the project.")

    # Task type - determines ML model type (classification, detection, etc.)
    task_type: TaskType = Field(default=TaskType.CLASSIFICATION, description="Type of ML task for active learning.")

    query_strategy_id: Optional[str] = Field(default=None, foreign_key="query_strategy.id",
                                             description="System-level query strategy id.")
    base_model_id: Optional[str] = Field(default=None, foreign_key="base_model.id",
                                         description="System-level base model id.")
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE, description="Current status of the project.")

    # JSON fields
    labels: List[Dict[str, str]] = Field(default=[], sa_column=Column(JSON),
                                         description="List of labels/classes defined for the project.")
    al_config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                      description="Configuration for Active Learning strategy.")
    model_settings: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                           description="Configuration for the model architecture.")


class Project(ProjectBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Project.
    Used for active learning training, can link to multiple Datasets.
    """
    # Relationships
    dataset_links: List["ProjectDataset"] = Relationship(back_populates="project")
    model_versions: List["ModelVersion"] = Relationship(back_populates="project")
    query_strategy: Optional["QueryStrategy"] = Relationship(back_populates="projects")
    base_model: Optional["BaseModel"] = Relationship(back_populates="projects")


class ProjectCreate(ProjectBase):
    """
    Model for creating a new Project.
    """
    pass


class ProjectStats(SQLModel):
    """Statistics for a project."""
    total_datasets: int = 0
    total_samples: int = 0
    labeled_samples: int = 0
    accuracy: float = 0.0


class ProjectRead(ProjectBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Project data (response model).
    """
    stats: Optional[ProjectStats] = Field(default_factory=ProjectStats)


class ProjectUpdate(SQLModel):
    """
    Model for updating an existing Project.
    """
    name: Optional[str] = None
    description: Optional[str] = None
    labels: Optional[List[Dict[str, str]]] = None
    al_config: Optional[Dict[str, Any]] = None
    model_settings: Optional[Dict[str, Any]] = None
    status: Optional[ProjectStatus] = None
    query_strategy_id: Optional[str] = None
    base_model_id: Optional[str] = None
