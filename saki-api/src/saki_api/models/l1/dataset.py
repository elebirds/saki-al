"""
Dataset model.

A Dataset represents a batch of uploaded ORIGINAL samples, not been annotated.
---
数据集Dataset，表示一批上传的、未标注的原始样本，其自身并不包含标注信息。
它是一个独立的实体，可以关联到多个项目中。
"""
import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import DatasetType
from saki_api.models.user import User

if TYPE_CHECKING:
    from saki_api.models.l1.sample import Sample
    from saki_api.models.l2.project import ProjectDataset


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
    type: DatasetType = Field(
        default=DatasetType.CLASSIC,
        description="Type of annotation system/interface for this dataset."
    )


class Dataset(DatasetBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Dataset.
    
    Independent entity for data annotation that can be linked to multiple projects.
    Members are managed through the ResourceMember table.
    """
    __tablename__ = "dataset"

    owner_id: uuid.UUID = Field(
        foreign_key="user.id",
        index=True,
        description="Owner of the dataset"
    )

    owner: "User" = Relationship(sa_relationship_kwargs={"viewonly": True})

    # Relationship to samples (one-to-many)
    samples: List["Sample"] = Relationship(back_populates="dataset")

    # Relationship to projects through link table (many-to-many)
    project_links: List["ProjectDataset"] = Relationship(back_populates="dataset")
