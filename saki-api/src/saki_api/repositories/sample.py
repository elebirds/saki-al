"""
Sample Repository - Data access layer for Sample operations.
"""

import uuid
from typing import List, Any

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l1.sample import Sample
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas.pagination import PaginationResponse


class SampleRepository(BaseRepository[Sample]):
    """Repository for Sample data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Sample, session)

    async def get_by_dataset(
            self,
            dataset_id: uuid.UUID,
            order_by: List[Any] | None = None,
    ) -> List[Sample]:
        """Get all samples in a dataset without pagination."""
        return await self.list(
            filters=[Sample.dataset_id == dataset_id],
            order_by=order_by,
        )

    async def get_by_dataset_paginated(
            self,
            dataset_id: uuid.UUID,
            pagination: Pagination = Pagination(),
            order_by: List[Any] | None = None,
    ) -> PaginationResponse[Sample]:
        """Get samples in a dataset with pagination."""
        return await self.list_paginated(
            pagination=pagination,
            filters=[Sample.dataset_id == dataset_id],
            order_by=order_by,
        )
