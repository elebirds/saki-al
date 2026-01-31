"""
Dataset Repository - Data access layer for Dataset operations.
"""

import uuid
from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l1.dataset import Dataset
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination


class DatasetRepository(BaseRepository[Dataset]):
    """Repository for Dataset data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Dataset, session)

    async def get_by_owner(self, owner_id: uuid.UUID, pagination: Pagination = Pagination()) -> List[Dataset]:
        """Get all datasets owned by a user."""
        return await self.list(
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
