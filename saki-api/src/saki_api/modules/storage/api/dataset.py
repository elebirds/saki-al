from uuid import UUID

from pydantic import ConfigDict
from sqlmodel import SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin
from saki_api.modules.storage.domain.dataset import DatasetBase


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
    is_public: bool | None = None


class DatasetRead(DatasetBase, TimestampMixin, UUIDMixin):
    """
    Schema for reading a dataset.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    owner_id: UUID
