from typing import List, Optional, Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import SampleStatus

if TYPE_CHECKING:
    from saki_api.models.dataset import Dataset
    from saki_api.models.annotation import Annotation


class SampleBase(SQLModel):
    """
    Base model for Sample.
    A Sample represents a single data item (e.g., image, time series).
    Samples belong to a Dataset, not directly to a Project.
    """
    dataset_id: str = Field(foreign_key="dataset.id", index=True,
                            description="ID of the dataset this sample belongs to.")
    name: str = Field(description="Name of the sample, which is the filename by default.")
    url: str = Field(default=None, description="Public URL to access the data.")
    remark: str = Field(default="", description="Remark associated with the sample.")

    status: SampleStatus = Field(default=SampleStatus.UNLABELED, index=True,
                                 description="Annotation status of the sample.")

    # tags: List[str] = Field(default=[], description="List of tags associated with the sample.")
    # TODO: add tags in sample.

    meta_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON),
                                      description="Additional metadata for the sample.")


class Sample(SampleBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Sample.
    Belongs to a Dataset. Can be used in multiple Projects through the Dataset link.
    """
    dataset: "Dataset" = Relationship(back_populates="samples")
    annotations: List["Annotation"] = Relationship(back_populates="sample")


class SampleCreate(SQLModel):
    """
    Model for creating a new Sample.
    """
    dataset_id: str = Field(description="ID of the dataset this sample belongs to.")
    name: str = Field(description="Name of the sample.")
    url: str = Field(default=None, description="Public URL to access the data.")
    remark: str = Field(default="", description="Remark associated with the sample.")
    meta_data: Dict[str, Any] = Field(default={}, description="Additional metadata for the sample.")


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
    remark: Optional[str] = None
    meta_data: Optional[Dict[str, Any]] = None
