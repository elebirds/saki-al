"""
Sample model for logical data layer.

Sample is the smallest logical unit in a dataset, grouping multiple related Assets.
This implements the physical-logical decoupling: Sample no longer stores annotation status,
as annotations are managed through the Git-like version control layer.
---
样本模型，用于逻辑数据层。
Sample 是数据集中最小的逻辑单元，负责将多个相关的 Asset 进行分组。
"""
import uuid
from typing import Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.storage.dataset import Dataset


class SampleBase(SQLModel):
    """
    Base model for Sample.
    A Sample represents a logical data unit grouping multiple physical Assets.
    """
    dataset_id: uuid.UUID = Field(
        foreign_key="dataset.id",
        index=True,
        description="ID of the dataset this sample belongs to."
    )

    name: str = Field(
        index=True,
        description="Name of the sample, typically the primary filename."
    )

    # Core field: maps logical roles to physical asset IDs
    # Example: {"raw_text": "asset_uuid_1", "lut": "asset_uuid_2", "image_main": "asset_uuid_3"}
    asset_group: Dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Maps logical asset roles to Asset IDs (e.g., raw_text, lut, image_main)."
    )

    # Primary asset for display (must be an image for frontend rendering)
    # This is the asset shown in dataset preview/listing
    primary_asset_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the primary asset (must be an image) for frontend display."
    )

    remark: str = Field(
        default="",
        description="Remark associated with the sample."
    )

    # Additional metadata (not physical, but sample-level logic)
    meta_info: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Additional sample-level metadata."
    )


class Sample(SampleBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Sample.
    Belongs to a Dataset.
    """
    __tablename__ = "sample"

    dataset: "Dataset" = Relationship(back_populates="samples")
