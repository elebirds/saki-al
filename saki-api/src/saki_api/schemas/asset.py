"""
Asset Schemas - Request and response models for asset operations.

Provides models for:
- AssetCreate: File upload requests
- AssetUpdate: Metadata updates
- AssetRead: Asset detail responses
- AssetUploadResponse: Upload completion response with presigned URL
- AssetDownloadResponse: Download information response
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from saki_api.models.enums import StorageType
from saki_api.models.l1.asset import AssetBase


# ========== Request/Input Schemas ==========

class AssetCreate(AssetBase):
    """
    Schema for creating/uploading an asset.
    
    All fields from AssetBase are required for asset creation.
    """
    pass


class AssetUpdate(BaseModel):
    """
    Schema for updating asset metadata.
    
    Only metadata can be updated after creation.
    Core asset properties are immutable.
    """
    meta_info: Optional[Dict[str, Any]] = Field(
        None,
        description="Updated metadata (merged with existing)"
    )


# ========== Response Schemas ==========

class AssetRead(AssetBase):
    """
    Schema for reading/returning asset details.
    
    Includes database metadata (id, created_at, updated_at).
    """
    id: UUID = Field(description="Asset UUID primary key")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class AssetUploadResponse(BaseModel):
    """
    Response model for successful asset upload.
    
    Includes the asset details plus a presigned download URL.
    """
    asset: AssetRead = Field(description="Asset details")
    download_url: str = Field(
        description="Presigned URL for downloading the asset (valid for 1 hour)"
    )
    is_duplicate: bool = Field(
        default=False,
        description="Whether this was a duplicate (asset already existed)"
    )

    model_config = ConfigDict(from_attributes=True)


class AssetDownloadResponse(BaseModel):
    """
    Response model for asset download information.
    
    Provides the presigned URL without exposing asset details.
    """
    asset_id: UUID = Field(description="Asset UUID")
    download_url: str = Field(description="Presigned URL for download")
    expires_in: int = Field(
        default=3600,
        description="URL expiration time in seconds"
    )
    filename: str = Field(description="Original filename for download")

    model_config = ConfigDict(from_attributes=True)


class AssetMetadataResponse(BaseModel):
    """
    Response model for asset metadata extraction.
    
    Returns metadata and physical properties without download URL.
    """
    asset_id: UUID = Field(description="Asset UUID")
    original_filename: str = Field(description="Original filename")
    mime_type: str = Field(description="MIME type")
    size: int = Field(description="File size in bytes")
    extension: str = Field(description="File extension")
    storage_type: StorageType = Field(description="Storage type (S3, LOCAL, etc.)")
    meta_info: Dict[str, Any] = Field(
        description="Physical metadata (dimensions, duration, satellite data, etc.)"
    )
    created_at: datetime = Field(description="Upload timestamp")

    model_config = ConfigDict(from_attributes=True)


# ========== List Response Schemas ==========

class AssetListItem(BaseModel):
    """
    Simplified asset item for list responses.
    
    Reduces payload size by excluding large metadata fields.
    """
    id: UUID
    original_filename: str
    extension: str
    mime_type: str
    size: int
    created_at: datetime
    storage_type: StorageType

    model_config = ConfigDict(from_attributes=True)


class AssetListResponse(BaseModel):
    """
    Paginated list response for assets.
    """
    items: list[AssetListItem]
    total: int = Field(description="Total number of assets")
    offset: int = Field(description="Query offset")
    limit: int = Field(description="Query limit")

    model_config = ConfigDict(from_attributes=True)


# ========== Statistics Schemas ==========

class AssetStorageStats(BaseModel):
    """
    Storage statistics by file type.
    """
    extension: str = Field(description="File extension (e.g., .jpg)")
    count: int = Field(description="Number of files")
    total_size: int = Field(description="Total size in bytes")
    avg_size: float = Field(description="Average size per file")

    model_config = ConfigDict(from_attributes=True)
