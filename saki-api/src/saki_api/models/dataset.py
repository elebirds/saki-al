"""
Dataset model.

A Dataset represents a batch of uploaded data for annotation.
Datasets are independent entities that can be:
- Used for data annotation
- Exported for external use
- Linked to training projects for active learning
"""

from typing import List, Optional, TYPE_CHECKING

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import AnnotationSystemType
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.sample import Sample
    from saki_api.models.project import ProjectDataset
    from saki_api.models.label import Label


class DatasetBase(SQLModel):
    """
    Base model for Dataset.
    """
    name: str = Field(
        max_length=200,
        description="Name of the dataset/batch."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Description of the dataset."
    )
    annotation_system: AnnotationSystemType = Field(
        default=AnnotationSystemType.CLASSIC,
        description="Type of annotation system/interface for this dataset."
    )


class Dataset(DatasetBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Dataset.
    
    Independent entity for data annotation that can be linked to multiple projects.
    Members are managed through the ResourceMember table.
    """
    __tablename__ = "dataset"
    
    owner_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="Owner of the dataset"
    )

    # Relationship to samples (one-to-many)
    samples: List["Sample"] = Relationship(back_populates="dataset")

    # Relationship to labels (one-to-many)
    labels: List["Label"] = Relationship(back_populates="dataset")

    # Relationship to projects through link table (many-to-many)
    project_links: List["ProjectDataset"] = Relationship(back_populates="dataset")
    
    # Note: Members are now managed through ResourceMember table
    # Use ResourceMember.resource_type == 'dataset' and ResourceMember.resource_id == self.id


class DatasetCreate(SQLModel):
    """
    Model for creating a new Dataset.
    """
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    annotation_system: AnnotationSystemType = AnnotationSystemType.CLASSIC


class DatasetRead(SQLModel):
    """
    Model for reading Dataset data.
    """
    id: str
    name: str
    description: Optional[str] = None
    annotation_system: AnnotationSystemType
    owner_id: str = Field(description="Owner of the dataset")
    created_at: str
    updated_at: str
    
    # Statistics (computed)
    sample_count: int = Field(default=0, description="Number of samples in the dataset.")
    labeled_count: int = Field(default=0, description="Number of labeled samples.")
    
    # Optional: current user's role in this dataset
    user_role: Optional[str] = Field(default=None, description="Current user's role in this dataset")

    class Config:
        from_attributes = True


class DatasetUpdate(SQLModel):
    """
    Model for updating a Dataset.
    """
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
