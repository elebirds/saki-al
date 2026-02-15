"""Dataset Repository - Data access layer for Dataset operations."""

import uuid
from typing import List

from sqlalchemy import or_
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.access.domain.rbac import ResourceType, Permissions
from saki_api.modules.storage.domain.dataset import Dataset


class DatasetRepository(BaseRepository[Dataset]):
    """Repository for Dataset data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Dataset, session)

    async def get_by_owner(self, owner_id: uuid.UUID, pagination: Pagination = Pagination()) -> PaginationResponse[
        Dataset]:
        """Get datasets owned by a user with pagination."""
        return await self.list_paginated(
            pagination=pagination,
            filters=[Dataset.owner_id == owner_id]
        )

    async def is_owner(self, dataset_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Check if a user is the owner of a dataset.
        
        Args:
            dataset_id: Dataset ID
            user_id: User ID
            
        Returns:
            True if user is owner, False otherwise
        """
        dataset = await self.get_by_id(dataset_id)
        if not dataset:
            return False
        return dataset.owner_id == user_id

    async def list_in_permission_paginated(
            self,
            user_id: uuid.UUID,
            pagination: Pagination,
            q: str | None = None,
    ) -> PaginationResponse[Dataset]:
        checker = PermissionChecker(self.session)

        base_query = self.list_statement()
        if q:
            pattern = f"%{q.strip()}%"
            base_query = base_query.where(
                or_(
                    Dataset.name.ilike(pattern),
                    Dataset.description.ilike(pattern),
                )
            )
        filtered_stmt = await checker.filter_accessible_resources(
            user_id=user_id,
            resource_type=ResourceType.DATASET,
            required_permission=Permissions.DATASET_READ,
            base_query=base_query,
            resource_model=Dataset,
        )

        items_stmt = filtered_stmt.offset(pagination.offset).limit(pagination.limit)
        items_result = await self.session.exec(items_stmt)
        items = list(items_result.all())

        total_stmt = select(func.count()).select_from(filtered_stmt.subquery())
        total_result = await self.session.exec(total_stmt)
        total = total_result.one() or 0

        return PaginationResponse.from_items(items, total, pagination.offset, pagination.limit)

    async def list_in_permission(self, user_id: uuid.UUID) -> List[Dataset]:
        """List all accessible datasets without pagination (use sparingly)."""
        pagination = None
        checker = PermissionChecker(self.session)
        base_query = self.list_statement()
        filtered_stmt = await checker.filter_accessible_resources(
            user_id=user_id,
            resource_type=ResourceType.DATASET,
            required_permission=Permissions.DATASET_READ,
            base_query=base_query,
            resource_model=Dataset,
        )
        result = await self.session.exec(filtered_stmt)
        return list(result.all())
