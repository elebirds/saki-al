from typing import List, Optional, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import AnnotationSystemType

if TYPE_CHECKING:
    from saki_api.models.sample import Sample
    from saki_api.models.project import ProjectDataset
    from saki_api.models.label import Label
    from saki_api.models.permission import DatasetMember


class DatasetBase(SQLModel):
    """
    Base model for Dataset.
    A Dataset represents a batch of uploaded data for annotation.
    Datasets are independent entities that can be:
    - Used for data annotation
    - Exported for external use
    - Linked to training projects for active learning
    """
    name: str = Field(description="Name of the dataset/batch.")
    description: Optional[str] = Field(default=None, description="Description of the dataset.")
    
    # Annotation system type - determines which annotation UI to use
    annotation_system: AnnotationSystemType = Field(
        default=AnnotationSystemType.CLASSIC,
        description="Type of annotation system/interface for this dataset."
    )


class Dataset(DatasetBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Dataset.
    Independent entity for data annotation that can be linked to multiple projects.
    """
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
    
    # Relationship to members (resource-level permissions)
    members: List["DatasetMember"] = Relationship(back_populates="dataset")


class DatasetCreate(SQLModel):
    """
    Model for creating a new Dataset.
    """
    name: str
    description: Optional[str] = None
    annotation_system: AnnotationSystemType = AnnotationSystemType.CLASSIC
    # owner_id 在创建时自动设置为当前用户，不需要在请求中提供


class DatasetRead(DatasetBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Dataset data.
    """
    sample_count: int = Field(default=0, description="Number of samples in the dataset.")
    labeled_count: int = Field(default=0, description="Number of labeled samples.")


class DatasetUpdate(SQLModel):
    """
    Model for updating a Dataset.
    """
    name: Optional[str] = None
    description: Optional[str] = None
