from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON
from models.base import TimestampMixin, UUIDMixin
from models.enums import TaskType, ProjectStatus

if TYPE_CHECKING:
    from models.system_config import QueryStrategy, BaseModel

class ProjectBase(SQLModel):
    """
    Base model for Project, containing common fields.
    """
    name: str = Field(index=True, description="Name of the project.")
    description: Optional[str] = Field(default=None, description="Description of the project.")
    task_type: TaskType = Field(default=TaskType.CLASSIFICATION, description="Type of CV task (classification or detection).")
    query_strategy_id: Optional[str] = Field(default=None, foreign_key="query_strategy.id", description="System-level query strategy id.")
    base_model_id: Optional[str] = Field(default=None, foreign_key="base_model.id", description="System-level base model id.")
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
    query_strategy: Optional["QueryStrategy"] = Relationship(back_populates="projects")
    base_model: Optional["BaseModel"] = Relationship(back_populates="projects")

class ProjectCreate(ProjectBase):
    """
    Model for creating a new Project.
    """
    pass

class ProjectStats(SQLModel):
    totalSamples: int = 0
    labeledSamples: int = 0
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
