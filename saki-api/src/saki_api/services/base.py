"""
Base Service - Generic business logic layer.

Provides generic service operations with automatic dependency injection.
"""

import uuid
from typing import TypeVar, Generic, List, Type

from pydantic import BaseModel
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import FilterType, Pagination, OrderByType

ModelType = TypeVar("ModelType", bound=SQLModel)
RepoType = TypeVar("RepoType", bound=BaseRepository)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseService(Generic[ModelType, RepoType, CreateSchemaType, UpdateSchemaType]):
    """
    Generic service for business logic.
    """

    def __init__(
            self,
            model: Type[ModelType],
            repository_class: Type[RepoType],
            session: AsyncSession
    ):
        """
        Initialize service.
        
        Args:
            model: The SQLModel class
            repository_class: The Repo class
            session: The async database session
        """
        self.model = model
        self.session = session
        self.repository: RepoType = repository_class(session)

    async def get_by_id(self, record_id: uuid.UUID) -> ModelType | None:
        """
        Get a record by ID or none
        """
        return await self.repository.get_by_id(record_id)

    async def get_by_id_or_raise(self, record_id: uuid.UUID) -> ModelType:
        """
        Get a record by ID or raise 404.

        Args:
            record_id: The record ID

        Returns:
            The record

        Raises:
            HTTPException: If record not found
        """
        record = await self.repository.get_by_id(record_id)
        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")
        return record

    async def get_one(self, filters: FilterType = None) -> ModelType | None:
        return await self.repository.get_one(filters)

    async def get_one_or_raise(self, filters: FilterType = None) -> ModelType:
        record = await self.repository.get_one(filters)
        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with Filters {filters} not found")
        return record

    async def list(self, pagination: Pagination = Pagination(),
                   filters: FilterType = None,
                   order_by: OrderByType = None, ) -> List[ModelType]:
        """
        List all records with pagination, filtering, and ordering.
        """
        return await self.repository.list(pagination, filters, order_by)

    @transactional
    async def create(self, schema: CreateSchemaType) -> ModelType:
        """
        Create a new record.
        
        Args:
            schema: The creation schema
            
        Returns:
            The created record
        """
        data = schema.model_dump(exclude_unset=True)
        return await self.repository.create(data)

    @transactional
    async def update(
            self,
            record_id: uuid.UUID,
            schema: UpdateSchemaType
    ) -> ModelType:
        """
        Update an existing record.
        
        Args:
            record_id: The record ID
            schema: The update schema
            
        Returns:
            The updated record
        """
        return await self.repository.update_or_raise(record_id, schema.model_dump(exclude_unset=True))

    @transactional
    async def delete(self, record_id: uuid.UUID) -> ModelType:
        """
        Delete a record.
        
        Args:
            record_id: The record ID
            
        Returns:
            The deleted record
        """
        # Get the record first to return it
        record = await self.get_by_id(record_id)

        # Delete the record
        success = await self.repository.delete(record_id)
        if not success:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")

        return record
