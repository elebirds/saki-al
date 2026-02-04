"""
Asset Repository - Data access layer for Asset operations.

Provides specialized queries for asset management including:
- Content-based lookup by hash
- Storage location queries
- Type filtering
- Garbage collection queries
"""

from typing import Optional, List

from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import StorageType
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.sample import Sample
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas.pagination import PaginationResponse


class AssetRepository(BaseRepository[Asset]):
    """Repository for Asset data access with specialized queries."""

    def __init__(self, session: AsyncSession):
        super().__init__(Asset, session)

    # ========== Content-Based Lookup ==========

    async def get_by_hash(self, file_hash: str) -> Optional[Asset]:
        """
        Get an asset by its content hash.
        
        Used for deduplication - check if content already exists.
        
        Args:
            file_hash: The SHA256 hash of the file content.
            
        Returns:
            The Asset if found, None otherwise.
        """
        stmt = select(Asset).where(Asset.hash == file_hash)
        result = await self.session.exec(stmt)
        return result.first()

    async def get_by_bucket_and_path(
            self,
            bucket: str,
            path: str
    ) -> Optional[Asset]:
        """
        Get asset by storage location (bucket + path).
        
        Useful for resolving assets by their physical location.
        
        Args:
            bucket: Storage bucket name
            path: File path within bucket
            
        Returns:
            The Asset if found, None otherwise.
        """
        stmt = select(Asset).where(
            (Asset.bucket == bucket) & (Asset.path == path)
        )
        result = await self.session.exec(stmt)
        return result.first()

    # ========== Type & Extension Queries ==========

    async def list_by_extension_paginated(
            self,
            extension: str,
            pagination: Pagination = Pagination()
    ) -> PaginationResponse[Asset]:
        """List assets with the given extension using pagination."""
        filters = [Asset.extension == extension]
        return await self.list_paginated(pagination=pagination, filters=filters)

    async def list_by_storage_type_paginated(
            self,
            storage_type: StorageType,
            pagination: Pagination = Pagination()
    ) -> PaginationResponse[Asset]:
        """List assets by storage type with pagination."""
        filters = [Asset.storage_type == storage_type]
        return await self.list_paginated(pagination=pagination, filters=filters)

    # ========== Statistics ==========

    async def count_by_extension(self, extension: str) -> int:
        """
        Count assets with specific extension.
        
        Args:
            extension: File extension
            
        Returns:
            Count of matching assets
        """
        stmt = select(func.count(Asset.id)).where(Asset.extension == extension)
        result = await self.session.exec(stmt)
        return result.first() or 0

    async def get_total_size_by_extension(self, extension: str) -> int:
        """
        Get total storage size for assets with specific extension.
        
        Args:
            extension: File extension
            
        Returns:
            Total size in bytes
        """
        stmt = select(func.sum(Asset.size)).where(Asset.extension == extension)
        result = await self.session.exec(stmt)
        return result.first() or 0

    # ========== Garbage Collection ==========

    async def get_orphaned_assets(
            self,
            pagination: Pagination = Pagination()
    ) -> List[Asset]:
        """
        Get assets not referenced by any Sample.
        
        An orphaned asset is one where:
        - The asset ID is not present in any Sample's asset_group JSON
        
        This query is complex due to JSON containment checks.
        Current implementation requires iterating and checking.
        
        Args:
            pagination: Pagination parameters
            
        Returns:
            List of orphaned assets
        """
        # Get all assets
        stmt = select(Asset)
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        result = await self.session.exec(stmt)
        all_assets = result.all()

        # Get all asset IDs referenced in samples
        sample_stmt = select(Sample)
        sample_result = await self.session.exec(sample_stmt)
        all_samples = sample_result.all()

        referenced_asset_ids = set()
        for sample in all_samples:
            if sample.asset_group:
                for asset_id_str in sample.asset_group.values():
                    referenced_asset_ids.add(asset_id_str)

        # Filter orphaned assets
        orphaned = [
            asset for asset in all_assets
            if str(asset.id) not in referenced_asset_ids
        ]

        return orphaned

    async def delete_orphaned_assets(self) -> int:
        """
        Delete all orphaned assets from database.
        
        Warning: This only deletes DB records, not physical storage files.
        Use separately for storage cleanup.
        
        Returns:
            Number of deleted assets
        """
        orphaned = await self.get_orphaned_assets(Pagination(limit=10000))
        deleted_count = 0

        for asset in orphaned:
            await self.delete(asset.id)
            deleted_count += 1

        return deleted_count

    async def get_unused_by_size(self, min_size: int = 0) -> List[Asset]:
        """
        Get orphaned assets by minimum size (for cleanup prioritization).
        
        Args:
            min_size: Minimum file size in bytes
            
        Returns:
            List of large orphaned assets
        """
        orphaned = await self.get_orphaned_assets(Pagination(limit=10000))
        return [asset for asset in orphaned if asset.size >= min_size]
