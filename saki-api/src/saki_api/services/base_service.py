"""
Base Service - Generic business logic layer.

Provides generic service operations with automatic dependency injection.
"""

import uuid
from typing import TypeVar, Generic, List, Type, Dict, Any

from pydantic import BaseModel
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.repositories.base_repository import BaseRepository

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
        self.repository : RepoType = repository_class(model, session)

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

    async def get_one(self, filters: Dict[str, Any] | None = None) -> ModelType | None:
        return await self.repository.get_one(filters)

    async def get_one_or_raise(self, filters: Dict[str, Any] | None = None) -> ModelType:
        record = await self.repository.get_one(filters)
        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with Filters {filters} not found")
        return record

    async def list_all(
            self,
            skip: int = 0,
            limit: int = 100,
            filters: Dict[str, Any] | None = None
    ) -> List[ModelType]:
        """
        List all records with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            filters: Optional dictionary of field filters
            
        Returns:
            List of records
        """
        return await self.repository.list_all(skip=skip, limit=limit, filters=filters)

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
            
        Raises:
            HTTPException: If record not found
        """
        data = schema.model_dump(exclude_unset=True)
        record = await self.repository.update(record_id, data)

        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")

        return record

    @transactional
    async def delete(self, record_id: uuid.UUID) -> ModelType:
        """
        Delete a record.
        
        Args:
            record_id: The record ID
            
        Returns:
            The deleted record
            
        Raises:
            HTTPException: If record not found
        """
        # Get the record first to return it
        record = await self.get_by_id(record_id)

        # Delete the record
        success = await self.repository.delete(record_id)
        if not success:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")

        return record
