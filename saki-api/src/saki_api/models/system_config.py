from typing import Dict, Any, List, Optional, TYPE_CHECKING

from saki_api.models.base import TimestampMixin
from saki_api.models.enums import TaskType
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.project import Project
    from saki_api.models.model_version import ModelVersion


class QueryStrategyBase(SQLModel):
    """
    System-level query strategy configuration used by projects.
    """
    name: str = Field(description="Display name for the strategy.")
    description: Optional[str] = Field(default=None, description="What the strategy does.")
    entrypoint: Optional[str] = Field(default=None,
                                      description="Python import path to load the strategy implementation.")
    params_schema: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                          description="JSON schema for tunable parameters.")
    enabled: bool = Field(default=True, description="Whether the strategy is available for projects.")


class QueryStrategy(QueryStrategyBase, TimestampMixin, table=True):
    __tablename__ = "query_strategy"

    # Use a string slug (e.g., entropy_sampling) so configs are stable and human-readable.
    id: str = Field(primary_key=True, description="Stable identifier used in configs and AL engine.")

    # Relationships
    projects: List["Project"] = Relationship(back_populates="query_strategy")


class QueryStrategyCreate(QueryStrategyBase):
    id: str


class QueryStrategyRead(QueryStrategyBase, TimestampMixin):
    id: str


class QueryStrategyUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    entrypoint: Optional[str] = None
    params_schema: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class BaseModelBase(SQLModel):
    """
    System-level base/foundation model definition (e.g., resnet50, yolov8n).
    """
    name: str = Field(description="Display name for the base model.")
    task_type: TaskType = Field(description="Task this model supports.")
    framework: Optional[str] = Field(default=None, description="DL framework (pytorch/tensorflow/etc).")
    provider: Optional[str] = Field(default=None, description="Provider or source (torchvision, ultralytics, hf, etc).")
    artifact_uri: Optional[str] = Field(default=None, description="Location of pretrained weights or model id.")
    default_config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                           description="Default hyperparameters/config.")
    description: Optional[str] = Field(default=None, description="Notes about the base model.")
    enabled: bool = Field(default=True, description="Whether the base model is selectable.")


class BaseModel(BaseModelBase, TimestampMixin, table=True):
    __tablename__ = "base_model"

    id: str = Field(primary_key=True, description="Stable identifier for referencing this base model.")

    # Relationships
    projects: List["Project"] = Relationship(back_populates="base_model")
    model_versions: List["ModelVersion"] = Relationship(back_populates="base_model")


class BaseModelCreate(BaseModelBase):
    id: str


class BaseModelRead(BaseModelBase, TimestampMixin):
    id: str


class BaseModelUpdate(SQLModel):
    name: Optional[str] = None
    task_type: Optional[TaskType] = None
    framework: Optional[str] = None
    provider: Optional[str] = None
    artifact_uri: Optional[str] = None
    default_config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
