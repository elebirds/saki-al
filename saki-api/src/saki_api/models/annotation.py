from typing import Dict, Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin


class AnnotationBase(SQLModel):
    """
    Base model for Annotation.
    Stores the actual labeling data for a sample.
    """
    sample_id: str = Field(foreign_key="sample.id", index=True, description="ID of the sample being annotated.")
    data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                 description="The annotation data (e.g., bounding boxes, class IDs).")
    annotator_id: Optional[str] = Field(default=None,
                                        description="ID of the user or system that created the annotation.")


class Annotation(AnnotationBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Annotation.
    """
    sample: "Sample" = Relationship(back_populates="annotations")


class AnnotationCreate(AnnotationBase):
    """
    Model for creating a new Annotation.
    """
    pass


class AnnotationRead(AnnotationBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Annotation data.
    """
    pass


class AnnotationUpdate(SQLModel):
    """
    Model for updating an Annotation.
    """
    data: Optional[Dict[str, Any]] = None
