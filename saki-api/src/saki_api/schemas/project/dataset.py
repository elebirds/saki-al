from uuid import UUID

from sqlmodel import SQLModel

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.l1.dataset import DatasetBase


class DatasetCreate(DatasetBase):
    """
    Schema for creating a dataset.
    """
    pass


class DatasetUpdate(SQLModel):
    """
    Schema for updating a dataset.
    """
    name: str | None = None
    description: str | None = None
    allow_duplicate_sample_names: bool | None = None


class DatasetRead(DatasetBase, TimestampMixin, UUIDMixin):
    """
    Schema for reading a dataset.
    """
    owner_id: UUID
