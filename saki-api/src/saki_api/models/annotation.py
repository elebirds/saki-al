"""
Annotation model for storing annotation data.
Annotations belong to Samples and reference Labels.
"""
from typing import Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.sample import Sample
    from saki_api.models.label import Label


class AnnotationBase(SQLModel):
    """
    Base model for Annotation.
    Stores the actual labeling data for a sample.
    """
    sample_id: str = Field(foreign_key="sample.id", index=True, description="ID of the sample being annotated.")
    label_id: str = Field(foreign_key="label.id", index=True, description="ID of the label for this annotation.")
    data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                 description="The annotation data (e.g., bounding boxes, class IDs).")
    annotator_id: Optional[str] = Field(default=None,
                                        description="ID of the user or system that created the annotation.")


class Annotation(AnnotationBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Annotation.
    """
    sample: "Sample" = Relationship(back_populates="annotations")
    label: "Label" = Relationship(back_populates="annotations")


class AnnotationCreate(SQLModel):
    """
    Model for creating a new Annotation.
    """
    sample_id: str
    label_id: str
    data: Dict[str, Any] = {}
    annotator_id: Optional[str] = None


class AnnotationRead(AnnotationBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Annotation data.
    """
    # Include label info for convenience
    label_name: Optional[str] = None
    label_color: Optional[str] = None


class AnnotationUpdate(SQLModel):
    """
    Model for updating an Annotation.
    """
    label_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
