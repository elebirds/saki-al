from typing import Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import ModelStatus

if TYPE_CHECKING:
    from saki_api.models.system_config import BaseModel


class ModelVersionBase(SQLModel):
    """
    Base model for ModelVersion.
    Tracks the history of trained models for a project.
    """
    project_id: str = Field(foreign_key="project.id", index=True, description="ID of the project.")
    base_model_id: Optional[str] = Field(default=None, foreign_key="base_model.id", index=True,
                                         description="Base model this version fine-tunes.")
    parent_version_id: Optional[str] = Field(default=None, foreign_key="modelversion.id",
                                             description="Optional parent model version for lineage.")
    name: str = Field(description="Name or tag for this model version.")
    description: Optional[str] = Field(default=None, description="Description of the model version.")
    metrics: Dict[str, float] = Field(default={}, sa_column=Column(JSON),
                                      description="Performance metrics (e.g., accuracy, mAP).")
    path_to_weights: Optional[str] = Field(default=None, description="File path to the saved model weights.")
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                   description="Hyperparameters and configuration used for training.")
    status: ModelStatus = Field(default=ModelStatus.TRAINING, description="Current status of the model training.")


class ModelVersion(ModelVersionBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for ModelVersion.
    """
    project: "Project" = Relationship(back_populates="model_versions")
    base_model: Optional["BaseModel"] = Relationship(back_populates="model_versions")


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
    config: Optional[Dict[str, Any]] = None
    base_model_id: Optional[str] = None
    parent_version_id: Optional[str] = None
