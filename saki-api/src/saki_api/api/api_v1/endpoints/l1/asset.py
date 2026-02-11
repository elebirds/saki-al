"""
Asset API Endpoints - REST API for asset management.

Provides endpoints for:
- File upload with deduplication
- Asset retrieval and metadata
- Presigned URL generation
- Asset listing and filtering
- Storage statistics
"""

from loguru import logger
import uuid
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Query, Path, HTTPException, status, Depends

from saki_api.api.service_deps import AssetServiceDep
from saki_api.core.rbac.dependencies import require_permission
from saki_api.models import Permissions
from saki_api.models.enums import StorageType
from saki_api.models.l1.asset import Asset
from saki_api.repositories.query import Pagination
from saki_api.schemas.asset import (
    AssetRead,
    AssetUploadResponse,
    AssetDownloadResponse,
    AssetMetadataResponse,
    AssetListItem,
    AssetStorageStats,
)


from saki_api.schemas.pagination import PaginationResponse

router = APIRouter()


def to_list_item(asset: Asset | AssetRead) -> AssetListItem:
    """Convert an asset model/read schema to a lightweight list item."""
    return AssetListItem(
        id=asset.id,
        original_filename=asset.original_filename,
        extension=asset.extension,
        mime_type=asset.mime_type,
        size=asset.size,
        created_at=asset.created_at,
        storage_type=asset.storage_type,
    )


# ========== Asset Upload ==========

@router.post(
    "/upload",
    response_model=AssetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and create/get asset",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_CREATE_ALL))],
    responses={
        201: {"description": "Asset created or retrieved (duplicate)"},
        400: {"description": "Invalid file or upload failed"}
    }
)
async def upload_asset(
        service: AssetServiceDep,
        file: UploadFile = File(..., description="File to upload"),
) -> AssetUploadResponse:
    """
    Upload a file and create/return asset record.
    
    Implements content-addressable storage:
    1. Calculate SHA256 hash of the file
    2. Check if asset exists (deduplication)
    3. If not exists: upload to MinIO and create DB record
    4. Return asset with presigned download URL
    
    If the exact same file (by hash) already exists, returns the existing
    asset without uploading again (deduplication).
    """
    # Upload file and get/create asset
    asset = await service.upload_file(file)

    # Get presigned download URL (valid for 1 hour)
    download_url = await service.get_presigned_download_url(asset.id)

    # Check if this was a duplicate
    is_duplicate = False  # We could track this in the service if needed

    return AssetUploadResponse(
        asset=asset,
        download_url=download_url,
        is_duplicate=is_duplicate
    )


# ========== Asset Retrieval ==========

@router.get(
    "/{asset_id}",
    response_model=AssetRead,
    summary="Get asset details",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
    responses={404: {"description": "Asset not found"}}
)
async def get_asset(
        asset_id: uuid.UUID,
        service: AssetServiceDep,
) -> AssetRead:
    """Get asset details by ID."""
    return AssetRead.model_validate(await service.get_by_id_or_raise(asset_id))


@router.get(
    "/hash/{file_hash}",
    response_model=Optional[AssetRead],
    summary="Get asset by content hash",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
    responses={404: {"description": "Asset not found"}}
)
async def get_asset_by_hash(
        service: AssetServiceDep,
        file_hash: str = Path(..., min_length=64, max_length=64, description="SHA256 hash"),
) -> Optional[AssetRead]:
    """Get asset by its SHA256 content hash."""
    asset = await service.get_by_hash(file_hash)

    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    return asset


# ========== Presigned URLs ==========

@router.get(
    "/{asset_id}/download-url",
    response_model=AssetDownloadResponse,
    summary="Get presigned download URL",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
    responses={404: {"description": "Asset not found"}}
)
async def get_download_url(
        service: AssetServiceDep,
        asset_id: uuid.UUID,
        expires_in_hours: int = Query(default=1, ge=1, le=24, description="URL expiration in hours"),
) -> AssetDownloadResponse:
    """
    Get a presigned URL for downloading the asset.
    
    The URL is valid for the specified duration (default 1 hour).
    No authentication required to download using the presigned URL.
    """
    asset = await service.get_by_id_or_raise(asset_id)
    download_url = await service.get_presigned_download_url(asset_id, expires_in_hours)

    return AssetDownloadResponse(
        asset_id=asset_id,
        download_url=download_url,
        expires_in=expires_in_hours * 3600,
        filename=asset.original_filename
    )


# ========== Asset Metadata ==========

@router.get(
    "/{asset_id}/metadata",
    response_model=AssetMetadataResponse,
    summary="Get asset metadata",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
    responses={404: {"description": "Asset not found"}}
)
async def get_asset_metadata(
        asset_id: uuid.UUID,
        service: AssetServiceDep,
) -> AssetMetadataResponse:
    """
    Get asset metadata without exposing the download URL.
    
    Returns information like file size, MIME type, physical metadata, etc.
    """
    asset = await service.get_by_id_or_raise(asset_id)
    return AssetMetadataResponse(
        asset_id=asset.id,
        original_filename=asset.original_filename,
        mime_type=asset.mime_type,
        size=asset.size,
        extension=asset.extension,
        storage_type=asset.storage_type,
        meta_info=asset.meta_info,
        created_at=asset.created_at
    )


# ========== Asset Listing ==========

@router.get(
    "",
    response_model=PaginationResponse[AssetListItem],
    summary="List assets with pagination",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
)
async def list_assets(
        service: AssetServiceDep,
        extension: Optional[str] = Query(None, description="Filter by extension (e.g. .jpg)"),
        storage_type: Optional[StorageType] = Query(None, description="Filter by storage type"),
        page: int = Query(default=1, ge=1, description="Page number (1-based)"),
        limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> PaginationResponse[AssetListItem]:
    """List assets with optional extension/storage type filters."""
    pagination = Pagination.from_page(page=page, limit=limit)

    if extension:
        assets = await service.list_by_extension(extension, pagination)
    elif storage_type:
        assets = await service.list_by_storage_type(storage_type, pagination)
    else:
        assets = await service.list_paginated(pagination)

    return assets.map(to_list_item)


@router.get(
    "/by-extension/{extension}",
    response_model=PaginationResponse[AssetListItem],
    summary="List assets by file extension",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
)
async def list_assets_by_extension(
        extension: str,
        service: AssetServiceDep,
        page: int = Query(default=1, ge=1, description="Page number (1-based)"),
        limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> PaginationResponse[AssetListItem]:
    """List assets filtered by extension with pagination."""
    pagination = Pagination.from_page(page=page, limit=limit)
    assets = await service.list_by_extension(extension, pagination)
    return assets.map(to_list_item)


# ========== Asset Status ==========

@router.get(
    "/{asset_id}/exists",
    response_model=dict,
    summary="Check if asset file exists in storage",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
)
async def check_asset_exists(
        asset_id: uuid.UUID,
        service: AssetServiceDep,
) -> dict:
    """
    Check if an asset file still exists in storage.
    
    This can be used to verify storage integrity.
    """
    exists = await service.get_object_exists(asset_id)

    return {
        "asset_id": asset_id,
        "exists": exists
    }


# ========== Asset Deletion ==========

@router.delete(
    "/{asset_id}",
    response_model=dict,
    summary="Delete asset record",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_DELETE_ALL))],
    responses={404: {"description": "Asset not found"}}
)
async def delete_asset(
        asset_id: uuid.UUID,
        service: AssetServiceDep,
) -> dict:
    """
    Delete asset record from database.
    
    Note: This only removes the DB record, not the physical file from storage.
    Use DELETE /{asset_id}/hard-delete for permanent storage deletion.
    """
    asset = await service.delete(asset_id)

    return {
        "success": True,
        "asset_id": asset.id,
        "message": "Asset record deleted (file remains in storage)"
    }


@router.delete(
    "/{asset_id}/hard-delete",
    response_model=dict,
    summary="Permanently delete asset from storage (DESTRUCTIVE)",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_DELETE_ALL))],
    responses={404: {"description": "Asset not found"}, 400: {"description": "Deletion failed"}}
)
async def hard_delete_asset(
        asset_id: uuid.UUID,
        service: AssetServiceDep,
        confirm: bool = Query(False, description="Must be true to confirm deletion"),
) -> dict:
    """
    Permanently delete asset from storage.
    
    WARNING: This is a destructive operation and cannot be undone!
    Requires confirm=true query parameter.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to permanently delete"
        )

    asset = await service.get_by_id_or_raise(asset_id)

    # Delete from storage
    await service.hard_delete_from_storage(asset_id)

    # Delete from database
    await service.delete(asset_id)

    logger.warning("资产已被永久删除 asset_id={} filename={}", asset_id, asset.original_filename)
    return {
        "success": True,
        "asset_id": asset_id,
        "message": "Asset permanently deleted from storage and database"
    }


# ========== Statistics ==========

@router.get(
    "/stats/by-extension",
    response_model=list[AssetStorageStats],
    summary="Get storage statistics by extension",
    dependencies=[Depends(require_permission(Permissions.SAMPLE_READ_ALL))],
)
async def get_storage_stats_by_extension(
        service: AssetServiceDep,
) -> list[AssetStorageStats]:
    """
    Get storage statistics grouped by file extension.
    
    Returns count and total size for each file type.
    """
    stats = await service.repository.list_storage_stats_by_extension()
    return [AssetStorageStats.model_validate(item) for item in stats]
