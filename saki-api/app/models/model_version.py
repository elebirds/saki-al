from typing import Dict, Any, Optional
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import ModelStatus

class ModelVersionBase(SQLModel):
    """
    Base model for ModelVersion.
    Tracks the history of trained models for a project.
    """
    project_id: str = Field(foreign_key="project.id", index=True, description="ID of the project.")
    name: str = Field(description="Name or tag for this model version.")
    description: Optional[str] = Field(default=None, description="Description of the model version.")
    metrics: Dict[str, float] = Field(default={}, sa_column=Column(JSON), description="Performance metrics (e.g., accuracy, mAP).")
    path_to_weights: Optional[str] = Field(default=None, description="File path to the saved model weights.")
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON), description="Hyperparameters and configuration used for training.")
    status: ModelStatus = Field(default=ModelStatus.TRAINING, description="Current status of the model training.")

class ModelVersion(ModelVersionBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for ModelVersion.
    """
    project: "Project" = Relationship(back_populates="model_versions")

class ModelVersionCreate(ModelVersionBase):
    """
    Model for creating a new ModelVersion.
    """
    pass

class ModelVersionRead(ModelVersionBase, TimestampMixin, UUIDMixin):
    """
    Model for reading ModelVersion data.
    """
    pass

class ModelVersionUpdate(SQLModel):
    """
    Model for updating a ModelVersion.
    """
    metrics: Optional[Dict[str, float]] = None
    status: Optional[ModelStatus] = None
    path_to_weights: Optional[str] = None
