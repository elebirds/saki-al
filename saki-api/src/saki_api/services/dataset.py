"""
Dataset Service.
"""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l1.dataset import Dataset
from saki_api.repositories.dataset import DatasetRepository
from saki_api.schemas.dataset import DatasetCreate, DatasetUpdate
from saki_api.services.base import BaseService


class DatasetService(BaseService[Dataset, DatasetRepository, DatasetCreate, DatasetUpdate]):
    """
    Service for managing Datasets.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Dataset, DatasetRepository, session)

    async def create_dataset(self, schema: DatasetCreate, owner_id: uuid.UUID) -> Dataset:
        """
        Create a new dataset with owner.
        """
        dataset = Dataset.model_dump(schema)
        dataset["owner_id"] = owner_id
        return await self.repository.create(dataset)
