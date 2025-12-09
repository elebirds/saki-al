from typing import List, Optional, Dict, Any
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import TaskType, ProjectStatus

class ProjectBase(SQLModel):
    """
    Base model for Project, containing common fields.
    """
    name: str = Field(index=True, description="Name of the project.")
    description: Optional[str] = Field(default=None, description="Description of the project.")
    task_type: TaskType = Field(default=TaskType.CLASSIFICATION, description="Type of CV task (classification or detection).")
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE, description="Current status of the project.")
    
    # JSON fields
    labels: List[Dict[str, str]] = Field(default=[], sa_column=Column(JSON), description="List of labels/classes defined for the project.")
    al_config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON), description="Configuration for Active Learning strategy.")
    model_settings: Dict[str, Any] = Field(default={}, sa_column=Column(JSON), description="Configuration for the model architecture.")

class Project(ProjectBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Project.
    """
    # Relationships
    datasets: List["Dataset"] = Relationship(back_populates="project")
    samples: List["Sample"] = Relationship(back_populates="project")
    model_versions: List["ModelVersion"] = Relationship(back_populates="project")

class ProjectCreate(ProjectBase):
    """
    Model for creating a new Project.
    """
    pass

class ProjectRead(ProjectBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Project data (response model).
    """
    pass

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
