"""
Asset model for physical data layer.

Asset represents a physical file stored in object storage (MinIO).
Uses content-addressable storage with hash-based IDs to prevent duplication.
---
物理资产Asset，存储在对象存储或本地
"""
from typing import Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import StorageType

if TYPE_CHECKING:
    pass


class AssetBase(SQLModel):
    """
    Base model for Asset.
    Physical file with content-addressable storage.
    """
    # 物理唯一性限制
    hash: str = Field(max_length=64, index=True, unique=True,
                      description="Content hash (MD5/SHA256) of the file for content-addressable storage.")

    # 存储定位
    storage_type: StorageType = Field(default=StorageType.S3, description="Storage type of the file (e.g., s3, local).")
    path: str = Field(max_length=1024, description="File path within the bucket/local.")
    bucket: str | None = Field(max_length=255,
                               description="Object storage bucket name, will be None if it stores in Local storage.")

    # 文件基本属性
    original_filename: str = Field(max_length=255, description="Original filename of the uploaded file.")
    extension: str = Field(max_length=31, description="File extension (e.g., .jpg, .png, .txt).")
    mime_type: str = Field(max_length=127,
                           description="MIME type of the file (e.g., image/png, application/octet-stream).")
    size: int = Field(default=0, description="File size in bytes.")

    # 其他元数据
    meta_info: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Metadata (dimensions, duration, satellite data, etc.)."
    )


class Asset(AssetBase, UUIDMixin, TimestampMixin, table=True):
    """
    Database model for Asset.
    Immutable physical file reference.
    """
    __tablename__ = "asset"
