from typing import List, Optional, Dict, Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import SampleStatus


class SampleBase(SQLModel):
    """
    Base model for Sample.
    A Sample represents a single image or data point.
    For specialized tasks like SATELLITE_FEDO, it can also represent a processed data file.
    """
    project_id: str = Field(foreign_key="project.id", index=True, description="ID of the project.")
    dataset_id: Optional[str] = Field(default=None, foreign_key="dataset.id", description="ID of the dataset batch.")
    file_path: str = Field(description="Path to the image file or data file on storage.")
    filename: Optional[str] = Field(default=None, description="Original filename of the uploaded file.")
    url: Optional[str] = Field(default=None, description="Public URL to access the image (if applicable).")
    status: SampleStatus = Field(default=SampleStatus.UNLABELED, index=True,
                                 description="Annotation status of the sample.")
    score: float = Field(default=0.0, index=True, description="Informativeness score calculated by AL strategy.")
    meta_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                      description="Additional metadata for the sample.")

    # Specialized task fields (for SATELLITE_FEDO etc.)
    parquet_path: Optional[str] = Field(default=None, description="Path to parquet file with processed data.")
    time_energy_image_path: Optional[str] = Field(default=None, description="Path to Time-Energy view image.")
    l_wd_image_path: Optional[str] = Field(default=None, description="Path to L-ωd view image.")
    lookup_table_path: Optional[str] = Field(default=None,
                                             description="Path to coordinate lookup table (L, ωd for each i,j).")


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
