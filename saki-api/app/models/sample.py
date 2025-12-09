from typing import List, Optional, Dict, Any
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import SampleStatus

class SampleBase(SQLModel):
    """
    Base model for Sample.
    A Sample represents a single image or data point.
    """
    project_id: str = Field(foreign_key="project.id", index=True, description="ID of the project.")
    dataset_id: Optional[str] = Field(default=None, foreign_key="dataset.id", description="ID of the dataset batch.")
    file_path: str = Field(description="Path to the image file on storage.")
    url: Optional[str] = Field(default=None, description="Public URL to access the image (if applicable).")
    status: SampleStatus = Field(default=SampleStatus.UNLABELED, index=True, description="Annotation status of the sample.")
    score: float = Field(default=0.0, index=True, description="Informativeness score calculated by AL strategy.")
    meta_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON), description="Additional metadata for the sample.")

class Sample(SampleBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Sample.
    """
    project: "Project" = Relationship(back_populates="samples")
    dataset: Optional["Dataset"] = Relationship(back_populates="samples")
    annotations: List["Annotation"] = Relationship(back_populates="sample")

class SampleCreate(SampleBase):
    """
    Model for creating a new Sample.
    """
    pass

class SampleRead(SampleBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Sample data.
    """
    pass

class SampleUpdate(SQLModel):
    """
    Model for updating a Sample.
    """
    status: Optional[SampleStatus] = None
    score: Optional[float] = None
    meta_data: Optional[Dict[str, Any]] = None
