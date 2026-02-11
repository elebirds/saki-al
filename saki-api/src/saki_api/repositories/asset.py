"""
Asset Repository - Data access layer for Asset operations.

Provides specialized queries for asset management including:
- Content-based lookup by hash
- Storage location queries
- Type filtering
- Garbage collection queries
"""

from datetime import datetime
import uuid
from typing import Optional, List, Set

from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import StorageType
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.sample import Sample
from saki_api.models.user import User
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas.pagination import PaginationResponse


class AssetRepository(BaseRepository[Asset]):
    """Repository for Asset data access with specialized queries."""

    AVATAR_ASSET_URI_PREFIX = "asset://"

    def __init__(self, session: AsyncSession):
        super().__init__(Asset, session)

    @classmethod
    def _parse_avatar_asset_id(cls, avatar_url: str | None) -> str | None:
        if not avatar_url or not avatar_url.startswith(cls.AVATAR_ASSET_URI_PREFIX):
            return None
        raw = avatar_url[len(cls.AVATAR_ASSET_URI_PREFIX):].strip()
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except ValueError:
            return None

    async def _collect_referenced_asset_ids(
            self,
            *,
            include_user_avatar_refs: bool = True,
    ) -> Set[str]:
        referenced_asset_ids: Set[str] = set()

        sample_stmt = select(Sample.primary_asset_id, Sample.asset_group)
        sample_rows = await self.session.exec(sample_stmt)
        for primary_asset_id, asset_group in sample_rows.all():
            if primary_asset_id:
                referenced_asset_ids.add(str(primary_asset_id))
            if isinstance(asset_group, dict):
                for asset_id_str in asset_group.values():
                    if asset_id_str:
                        referenced_asset_ids.add(str(asset_id_str))

        if include_user_avatar_refs:
            user_avatar_stmt = select(User.avatar_url).where(User.avatar_url.is_not(None))
            user_avatar_rows = await self.session.exec(user_avatar_stmt)
            for avatar_url in user_avatar_rows.all():
                parsed = self._parse_avatar_asset_id(avatar_url)
                if parsed:
                    referenced_asset_ids.add(parsed)

        return referenced_asset_ids

    async def is_referenced(
            self,
            asset_id: uuid.UUID,
            *,
            include_user_avatar_refs: bool = True,
    ) -> bool:
        referenced_asset_ids = await self._collect_referenced_asset_ids(
            include_user_avatar_refs=include_user_avatar_refs
        )
        return str(asset_id) in referenced_asset_ids

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

    async def list_storage_stats_by_extension(self) -> List[dict]:
        """Get aggregated storage stats grouped by extension."""
        stmt = (
            select(
                Asset.extension,
                func.count(Asset.id),
                func.coalesce(func.sum(Asset.size), 0),
                func.coalesce(func.avg(Asset.size), 0.0),
            )
            .group_by(Asset.extension)
            .order_by(func.count(Asset.id).desc(), Asset.extension.asc())
        )
        result = await self.session.exec(stmt)
        rows = result.all()
        return [
            {
                "extension": extension or "",
                "count": int(count or 0),
                "total_size": int(total_size or 0),
                "avg_size": float(avg_size or 0.0),
            }
            for extension, count, total_size, avg_size in rows
        ]

    # ========== Garbage Collection ==========

    async def get_orphaned_assets(
            self,
            pagination: Pagination = Pagination()
    ) -> List[Asset]:
        """
        Get assets not referenced by Sample records or user avatars.
        
        An orphaned asset is one where:
        - The asset ID is not present in Sample.primary_asset_id
        - The asset ID is not present in any Sample.asset_group JSON value
        - The asset ID is not referenced by User.avatar_url (asset://<uuid>)
        
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

        referenced_asset_ids = await self._collect_referenced_asset_ids()

        # Filter orphaned assets
        orphaned = [
            asset for asset in all_assets
            if str(asset.id) not in referenced_asset_ids
        ]

        return orphaned

    async def get_orphaned_assets_older_than(
            self,
            *,
            older_than: datetime,
            limit: int = 1000,
    ) -> List[Asset]:
        """
        Get orphaned assets created before the given timestamp.

        References include Sample primary/group assets and User.avatar_url asset refs.
        """
        limit = max(1, min(limit, 100000))

        asset_stmt = (
            select(Asset)
            .where(Asset.created_at <= older_than)
            .order_by(Asset.created_at.asc())
            .limit(limit)
        )
        asset_rows = await self.session.exec(asset_stmt)
        candidate_assets = list(asset_rows.all())
        if not candidate_assets:
            return []

        referenced_asset_ids = await self._collect_referenced_asset_ids()

        return [
            asset for asset in candidate_assets
            if str(asset.id) not in referenced_asset_ids
        ]

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
