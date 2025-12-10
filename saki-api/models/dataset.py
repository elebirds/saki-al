from typing import List, Optional
from sqlmodel import Field, SQLModel, Relationship
from models.base import TimestampMixin, UUIDMixin

class DatasetBase(SQLModel):
    """
    Base model for Dataset.
    A Dataset represents a batch of uploaded images within a Project.
    """
    name: str = Field(description="Name of the dataset/batch.")
    description: Optional[str] = Field(default=None, description="Description of the dataset.")
    project_id: str = Field(foreign_key="project.id", description="ID of the project this dataset belongs to.")

class Dataset(DatasetBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Dataset.
    """
    project: "Project" = Relationship(back_populates="datasets")
    samples: List["Sample"] = Relationship(back_populates="dataset")

class DatasetCreate(DatasetBase):
    """
    Model for creating a new Dataset.
    """
    pass

class DatasetRead(DatasetBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Dataset data.
    """
    pass

class DatasetUpdate(SQLModel):
    """
    Model for updating a Dataset.
    """
    name: Optional[str] = None
    description: Optional[str] = None
