"""
Base Repository - Generic data access layer for CRUD operations.

Provides generic async CRUD operations for SQLModel models.
"""

import uuid
from typing import TypeVar, Generic, Optional, List, Type, Any, Dict

from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

ModelType = TypeVar("ModelType", bound=SQLModel)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository for database operations.
    
    Provides standard CRUD operations:
    - get_by_id: Retrieve a single record by ID
    - list_all: List all records with pagination
    - create: Create a new record
    - update: Update an existing record
    - delete: Delete a record
    
    Usage:
        class UserRepository(BaseRepository[User]):
            pass
    """

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        """
        Initialize repository.
        
        Args:
            model: The SQLModel class
            session: The async database session
        """
        self.model = model
        self.session = session

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[ModelType]:
        """
        Get a record by ID.
        
        Args:
            record_id: The record ID
            
        Returns:
            The record if found, None otherwise
        """
        return await self.session.get(self.model, record_id)

    async def get_one(
            self,
            filters: Optional[Dict[str, Any]] = None
    ) -> Optional[ModelType]:
        """
        Get one record.

        Args:
            filters: Optional dictionary of field filters

        Returns:
            List of records
        """
        statement = select(self.model)

        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field):
                    statement = statement.where(getattr(self.model, field) == value)

        result = await self.session.exec(statement)
        # 使用 .first() 只取一条，即使匹配多条也只返回第一条
        return result.first()

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
        statement = select(self.model).offset(skip).limit(limit)

        # Apply filters if provided
        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field):
                    statement = statement.where(
                        getattr(self.model, field) == value
                    )

        result = await self.session.exec(statement)
        return list(result.all())

    async def create(self, data: Dict[str, Any]) -> ModelType:
        """
        Create a new record.
        
        Args:
            data: Dictionary of field values
            
        Returns:
            The created record
        """
        record = self.model(**data)
        self.session.add(record)
        # flush 会同步对象状态到数据库内存，触发 before_insert 事件
        await self.session.flush()
        # 刷新以获取数据库生成的字段（如审计字段、ID等）
        await self.session.refresh(record)
        return record

    async def update(
            self,
            record_id: uuid.UUID,
            data: Dict[str, Any]
    ) -> Optional[ModelType]:
        """
        Update an existing record.
        
        Args:
            record_id: The record ID
            data: Dictionary of field values to update
            
        Returns:
            The updated record if found, None otherwise
        """
        record = await self.get_by_id(record_id)
        if not record:
            return None

        for key, value in data.items():
            if hasattr(record, key):
                setattr(record, key, value)

        self.session.add(record)
        # flush 会同步对象状态到数据库内存，触发 before_insert 事件
        await self.session.flush()
        # 刷新以获取数据库生成的字段（如审计字段、ID等）
        await self.session.refresh(record)
        return record

    async def delete(self, record_id: uuid.UUID) -> bool:
        """
        Delete a record.
        
        Args:
            record_id: The record ID
            
        Returns:
            True if deleted, False if not found
        """
        record = await self.get_by_id(record_id)
        if not record:
            return False

        await self.session.delete(record)
        await self.session.flush()
        return True

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()

    async def refresh(self, record: ModelType) -> None:
        """Refresh a record from the database."""
        await self.session.refresh(record)

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self.session.rollback()
