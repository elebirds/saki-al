"""
Label model for annotation labels.
Labels belong to Datasets and are referenced by Annotations.
"""
from typing import Optional, TYPE_CHECKING, List

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.dataset import Dataset
    from saki_api.models.annotation import Annotation


class LabelBase(SQLModel):
    """
    Base model for Label.
    A Label represents a category/class for annotation within a dataset.
    """
    name: str = Field(description="Name of the label (e.g., 'Object', 'Background').")
    color: str = Field(default="#1890ff", description="Color code for the label (hex format).")
    description: Optional[str] = Field(default=None, description="Optional description of the label.")

    # Order for display purposes
    sort_order: int = Field(default=0, description="Order for displaying labels.")


class Label(LabelBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Label.
    Labels are defined per-dataset and referenced by annotations.
    """
    # Foreign key to Dataset
    dataset_id: str = Field(foreign_key="dataset.id", index=True,
                            description="ID of the dataset this label belongs to.")

    # Relationships
    dataset: "Dataset" = Relationship(back_populates="labels")
    annotations: List["Annotation"] = Relationship(back_populates="label")


class LabelCreate(SQLModel):
    """
    Model for creating a new Label.
    """
    name: str
    color: str = "#1890ff"
    description: Optional[str] = None
    sort_order: int = 0


class LabelRead(LabelBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Label data.
    """
    dataset_id: str
    annotation_count: int = Field(default=0, description="Number of annotations using this label.")


class LabelUpdate(SQLModel):
    """
    Model for updating a Label.
    """
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
