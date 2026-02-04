"""
Asset Service - Handles business logic for asset management.

Provides asset CRUD operations, deduplication, storage integration,
and presigned URL generation for secure asset access.
"""

import hashlib
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.db.transaction import transactional
from saki_api.models.enums import StorageType
from saki_api.models.l1.asset import Asset
from saki_api.repositories.asset import AssetRepository
from saki_api.repositories.query import Pagination, OrderByType
from saki_api.schemas.asset import AssetRead, AssetCreate, AssetUpdate
from saki_api.schemas.pagination import PaginationResponse
from saki_api.services.base import BaseService
from saki_api.utils.storage import get_storage_provider, StorageError


class AssetService(BaseService[Asset, AssetRepository, AssetCreate, AssetUpdate]):
    """
    Service for managing Assets with deduplication and storage integration.
    
    Features:
    - Content-addressable storage via SHA256 hashing
    - Automatic deduplication (same content = single file)
    - MinIO storage provider integration
    - Presigned URL generation for secure access
    - Reference counting for garbage collection
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Asset, AssetRepository, session)
        self.storage = get_storage_provider()

    # ========== Hash & Deduplication ==========

    async def calculate_file_hash(self, file: UploadFile) -> tuple[str, int]:
        """
        Calculate SHA256 hash of a file and return file size.
        
        Args:
            file: The uploaded file
            
        Returns:
            Tuple of (hash_hex_digest, file_size_bytes)
        """
        sha256_hash = hashlib.sha256()
        await file.seek(0)

        file_size = 0
        while chunk := await file.read(8192):
            sha256_hash.update(chunk)
            file_size += len(chunk)

        await file.seek(0)
        return sha256_hash.hexdigest(), file_size

    # ========== Asset Upload & Storage ==========

    @transactional
    async def upload_file(
            self,
            file: UploadFile,
            storage_type: StorageType = StorageType.S3,
            meta_info: Optional[dict] = None
    ) -> AssetRead:
        """
        Upload a file and create/return asset record.
        
        Implements content-addressable storage:
        1. Calculate SHA256 hash and file size in single pass
        2. Check if asset exists (deduplication)
        3. If not exists: upload to storage and create DB record
        4. Return asset
        
        Args:
            file: The uploaded file
            storage_type: Storage backend (S3 or LOCAL)
            meta_info: Optional metadata (dimensions, duration, etc.)
            
        Returns:
            AssetRead schema with asset details
            
        Raises:
            BadRequestAppException: If upload fails
        """
        # 1. Calculate hash and file size in a single pass
        file_hash, file_size = await self.calculate_file_hash(file)

        # 2. Check if asset already exists
        existing_asset = await self.repository.get_by_hash(file_hash)
        if existing_asset:
            return AssetRead.model_validate(existing_asset)

        # 3. Prepare file metadata
        original_filename = file.filename or "unknown"
        extension = Path(original_filename).suffix or ""
        mime_type = file.content_type or "application/octet-stream"

        # 4. Build storage path: assets/ab/abcdef123.../.../filename.ext
        object_name = f"assets/{file_hash[:2]}/{file_hash}/{original_filename}"

        # 5. Upload to storage
        try:
            self.storage.put_object(
                data=file.file,
                object_name=object_name,
                length=file_size,
                content_type=mime_type
            )
        except StorageError as e:
            raise BadRequestAppException(f"Failed to upload file to storage: {str(e)}")

        # 6. Create asset record
        asset_data = AssetCreate(
            hash=file_hash,
            storage_type=storage_type,
            path=object_name,
            bucket=settings.MINIO_BUCKET_NAME if storage_type == StorageType.S3 else None,
            original_filename=original_filename,
            extension=extension,
            mime_type=mime_type,
            size=file_size,
            meta_info=meta_info or {}
        )

        asset = await self.create(asset_data)
        return AssetRead.model_validate(asset)

    # ========== Asset Retrieval ==========

    async def get_by_hash(self, file_hash: str) -> Optional[AssetRead]:
        """
        Get asset by content hash.
        
        Args:
            file_hash: The SHA256 hash
            
        Returns:
            Asset if found, None otherwise
        """
        asset = await self.repository.get_by_hash(file_hash)
        return AssetRead.model_validate(asset) if asset else None

    async def get_by_bucket_and_path(
            self,
            bucket: str,
            path: str
    ) -> Optional[AssetRead]:
        """
        Get asset by bucket and path (storage location).
        
        Args:
            bucket: Storage bucket name
            path: File path within bucket
            
        Returns:
            Asset if found, None otherwise
        """
        asset = await self.repository.get_by_bucket_and_path(bucket, path)
        return AssetRead.model_validate(asset) if asset else None

    async def list_by_extension(
            self,
            extension: str,
            pagination: Pagination = Pagination(),
            order_by: OrderByType = None
    ) -> PaginationResponse[AssetRead]:
        """List assets by file extension with pagination."""
        filters = [Asset.extension == extension]
        assets = await self.list_paginated(pagination, filters, order_by)
        return assets.map(AssetRead.model_validate)

    async def list_by_storage_type(
            self,
            storage_type: StorageType,
            pagination: Pagination = Pagination(),
            order_by: OrderByType = None
    ) -> PaginationResponse[AssetRead]:
        """List assets by storage type (S3, LOCAL, etc.) with pagination."""
        filters = [Asset.storage_type == storage_type]
        assets = await self.list_paginated(pagination, filters, order_by)
        return assets.map(AssetRead.model_validate)

    # ========== Presigned URLs & Access ==========

    async def get_presigned_download_url(
            self,
            asset_id: uuid.UUID,
            expires_in_hours: int = 1
    ) -> str:
        """
        Get presigned URL for asset download.
        
        Used by frontend to download assets without exposing storage credentials.
        
        Args:
            asset_id: Asset UUID
            expires_in_hours: URL expiration time in hours
            
        Returns:
            Presigned URL string
            
        Raises:
            NotFoundAppException: If asset not found
        """
        asset = await self.get_by_id_or_raise(asset_id)

        try:
            expires_delta = timedelta(hours=expires_in_hours)
            return self.storage.get_presigned_url(asset.path, expires_delta)
        except StorageError as e:
            raise BadRequestAppException(f"Failed to generate presigned URL: {str(e)}")

    # ========== File Operations ==========

    async def download_to_local(
            self,
            asset_id: uuid.UUID,
            local_path: Path
    ) -> None:
        """
        Download asset file to local filesystem.
        
        Used for processing files that need local access (e.g., LUT files).
        
        Args:
            asset_id: Asset UUID
            local_path: Target local file path
            
        Raises:
            NotFoundAppException: If asset not found
            StorageError: If download fails
        """
        asset = await self.get_by_id_or_raise(asset_id)

        try:
            self.storage.download_file(asset.path, local_path)
        except StorageError as e:
            raise BadRequestAppException(f"Failed to download file: {str(e)}")

    async def get_object_exists(self, asset_id: uuid.UUID) -> bool:
        """
        Check if asset file exists in storage.
        
        Args:
            asset_id: Asset UUID
            
        Returns:
            True if file exists, False otherwise
            
        Raises:
            NotFoundAppException: If asset record not found
        """
        asset = await self.get_by_id_or_raise(asset_id)
        return self.storage.object_exists(asset.path)

    async def get_object_bytes(self, asset_id: uuid.UUID) -> bytes:
        """
        Read asset content from storage as bytes.
        
        Args:
            asset_id: Asset UUID
            
        Returns:
            Asset content bytes
            
        Raises:
            NotFoundAppException: If asset record not found
            BadRequestAppException: If storage read fails
        """
        asset = await self.get_by_id_or_raise(asset_id)
        try:
            return self.storage.get_object_bytes(asset.path)
        except StorageError as e:
            raise BadRequestAppException(f"Failed to read asset bytes: {str(e)}")

    # ========== Asset Deletion & Cleanup ==========

    @transactional
    async def delete(self, asset_id: uuid.UUID) -> AssetRead:
        """
        Delete asset and optionally remove from storage.
        
        Note: Currently only removes DB record. Physical deletion from storage
        should be handled by garbage collection tasks to prevent accidental data loss.
        
        Args:
            asset_id: Asset UUID
            
        Returns:
            Deleted asset record
            
        Raises:
            NotFoundAppException: If asset not found
        """
        # Get asset first
        asset = await self.get_by_id_or_raise(asset_id)

        # Delete from database
        await self.repository.delete(asset_id)

        # Note: We don't delete from storage here to prevent accidents
        # Use garbage collection tasks for cleanup

        return AssetRead.model_validate(asset)

    @transactional
    async def hard_delete_from_storage(self, asset_id: uuid.UUID) -> None:
        """
        Permanently delete asset from storage (DESTRUCTIVE).
        
        This is a dangerous operation - only use for confirmed cleanup.
        Consider garbage collection tasks instead.
        
        Args:
            asset_id: Asset UUID
            
        Raises:
            NotFoundAppException: If asset not found
            StorageError: If deletion fails
        """
        asset = await self.get_by_id_or_raise(asset_id)

        try:
            self.storage.delete_object(asset.path)
        except StorageError as e:
            raise BadRequestAppException(f"Failed to delete from storage: {str(e)}")

    # ========== Metadata Management ==========

    async def update_metadata(
            self,
            asset_id: uuid.UUID,
            meta_info: dict
    ) -> AssetRead:
        """
        Update asset metadata (dimensions, duration, satellite data, etc.).
        
        Args:
            asset_id: Asset UUID
            meta_info: Metadata dictionary to merge/update
            
        Returns:
            Updated asset
            
        Raises:
            NotFoundAppException: If asset not found
        """
        asset = await self.get_by_id_or_raise(asset_id)

        # Merge with existing metadata
        updated_meta = {**(asset.meta_info or {}), **meta_info}

        update_data = AssetUpdate(meta_info=updated_meta)
        updated = await self.repository.update_or_raise(
            asset_id,
            update_data.model_dump(exclude_unset=True)
        )

        return AssetRead.model_validate(updated)

    # ========== Garbage Collection ==========

    async def get_orphaned_assets(
            self,
            pagination: Pagination = Pagination()
    ) -> List[AssetRead]:
        """
        Get orphaned assets (not referenced by any Sample).
        
        Used for garbage collection to identify unreferenced files.
        
        Args:
            pagination: Pagination parameters
            
        Returns:
            List of orphaned assets
        """
        # This requires checking Sample.asset_group to find unreferenced assets
        # Implementation depends on Sample model structure
        orphaned = await self.repository.get_orphaned_assets(pagination)
        return [AssetRead.model_validate(asset) for asset in orphaned]

    @transactional
    async def cleanup_orphaned_assets(self) -> int:
        """
        Delete orphaned assets from database (without storage deletion).
        
        Returns:
            Number of deleted assets
        """
        deleted_count = await self.repository.delete_orphaned_assets()
        return deleted_count
