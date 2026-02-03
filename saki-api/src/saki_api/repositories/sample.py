"""
Sample Repository - Data access layer for Sample operations.
"""

import uuid
from typing import List, Any

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l1.sample import Sample
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination


class SampleRepository(BaseRepository[Sample]):
    """Repository for Sample data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Sample, session)

    async def get_by_dataset(
            self,
            dataset_id: uuid.UUID,
            pagination: Pagination = Pagination(),
            order_by: List[Any] | None = None,
    ) -> List[Sample]:
        """
        Get all samples in a dataset.
        """
        return await self.list(
            pagination=pagination,
            filters=[Sample.dataset_id == dataset_id],
            order_by=order_by,
        )
