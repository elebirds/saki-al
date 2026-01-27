"""
Base Service - Generic business logic layer.

Provides generic service operations with automatic dependency injection.
"""

import uuid
from typing import TypeVar, Generic, Optional, List, Type, Dict, Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models import User
from saki_api.repositories.base_repository import BaseRepository

ModelType = TypeVar("ModelType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Generic service for business logic.
    
    Provides standard CRUD operations with automatic dependency injection:
    - get_by_id: Get a single record by ID
    - list_all: List all records with pagination
    - create: Create a new record
    - create_with_owner: Create a record with automatic owner assignment
    - update: Update an existing record
    - delete: Delete a record
    
    Usage:
        class UserService(BaseService[User, UserCreate, UserUpdate]):
            def __init__(
                self,
                session: AsyncSession = Depends(get_session),
                current_user: User = Depends(get_current_user)
            ):
                super().__init__(User, session, current_user)
    """

    def __init__(
            self,
            model: Type[ModelType],
            session: AsyncSession,
            current_user: Optional[User] = None
    ):
        """
        Initialize service.
        
        Args:
            model: The SQLModel class
            session: The async database session
            current_user: The current authenticated user (optional)
        """
        self.model = model
        self.session = session
        self.current_user = current_user
        self.repository = BaseRepository[ModelType](model, session)

    async def get_by_id(self, record_id: uuid.UUID) -> ModelType:
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
            raise HTTPException(
                status_code=404,
                detail=f"{self.model.__name__} not found"
            )
        return record

    async def list_all(
            self,
            skip: int = 0,
            limit: int = 100,
            filters: Optional[Dict[str, Any]] = None
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

    async def create(self, schema: CreateSchemaType) -> ModelType:
        """
        Create a new record.
        
        Args:
            schema: The creation schema
            
        Returns:
            The created record
        """
        data = schema.model_dump(exclude_unset=True)
        record = await self.repository.create(data)
        await self.repository.commit()
        return record

    async def create_with_owner(self, schema: CreateSchemaType) -> ModelType:
        """
        Create a new record with automatic owner assignment.
        
        Automatically sets creator_id if the model has this field and
        current_user is available.
        
        Args:
            schema: The creation schema
            
        Returns:
            The created record
            
        Raises:
            HTTPException: If current_user is required but not available
        """
        data = schema.model_dump(exclude_unset=True)

        # Auto-assign creator_id if the model has this field
        if hasattr(self.model, 'creator_id'):
            if not self.current_user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required for this operation"
                )
            data['creator_id'] = self.current_user.id

        record = await self.repository.create(data)
        await self.repository.commit()
        return record

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
            raise HTTPException(
                status_code=404,
                detail=f"{self.model.__name__} not found"
            )

        await self.repository.commit()
        return record

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
            raise HTTPException(
                status_code=404,
                detail=f"{self.model.__name__} not found"
            )

        await self.repository.commit()
        return record
