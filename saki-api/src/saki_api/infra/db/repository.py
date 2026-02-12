"""
Base Repository - Generic data access layer for CRUD operations.

Provides generic async CRUD operations for SQLModel models.
"""

import uuid
from typing import TypeVar, Generic, Optional, List, Type, Any, Dict

from sqlalchemy import exists, func
from sqlalchemy.orm import joinedload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import SelectOfScalar

from saki_api.core.exceptions import NotFoundAppException
from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination, FilterType, OrderByType

ModelType = TypeVar("ModelType", bound=SQLModel)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository for database operations.
    
    Provides standard CRUD operations:
    - get_by_id: Retrieve a single record by ID
    - list: List records with pagination and ordering
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

    async def exists(self, filters: FilterType = None) -> bool:
        statement = select(exists().select_from(self.model))
        if filters: statement = statement.where(*filters)
        result = await self.session.exec(statement)
        return result.first() or False

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[ModelType]:
        """
        Get a record by ID.
        
        Args:
            record_id: The record ID
            
        Returns:
            The record if found, None otherwise
        """
        return await self.session.get(self.model, record_id)

    async def get_by_id_or_raise(self, record_id: uuid.UUID) -> ModelType:
        """
        Get a record by ID or raise NotFoundAppException.
        
        Args:
            record_id: The record ID
            
        Returns:
            The record
            
        Raises:
            NotFoundAppException: If record not found
        """
        record = await self.get_by_id(record_id)
        if not record:
            raise NotFoundAppException(
                f"{self.model.__name__} with ID {record_id} not found"
            )
        return record

    async def get_one(
            self,
            filters: FilterType = None,
            joinedloads: List[Any] = None,
    ) -> Optional[ModelType]:
        """
        Get one record.

        Args:
            filters: Optional dictionary of field filters
            joinedloads: Optional list of SQLAlchemy early loading records

        Returns:
            List of records
        """
        statement = select(self.model)

        if filters: statement = statement.where(*filters)

        if joinedloads:
            for jl in joinedloads:
                statement = statement.options(joinedload(jl))

        result = await self.session.exec(statement)
        # 使用 .first() 只取一条，即使匹配多条也只返回第一条
        return result.first()

    async def get_one_or_raise(
            self,
            filters: FilterType = None,
            joinedloads: List[Any] = None,
    ) -> ModelType:
        """
        Get one record or raise NotFoundAppException.
        
        Args:
            filters: Optional dictionary of field filters
            joinedloads: Optional list of SQLAlchemy early loading records
            
        Returns:
            The record
            
        Raises:
            NotFoundAppException: If record not found
        """
        record = await self.get_one(filters, joinedloads)
        if not record:
            filter_str = f" with filters {filters}" if filters else ""
            raise NotFoundAppException(
                f"{self.model.__name__}{filter_str} not found"
            )
        return record

    def list_statement(
            self,
            filters: FilterType | None = None,
            order_by: OrderByType | None = None,
            joinedloads: List[Any] | None = None,
    ) -> SelectOfScalar:
        """
        Build a base select statement with filters, ordering, and eager loading.
        """
        statement = select(self.model)
        if filters: statement = statement.where(*filters)
        if order_by: statement = statement.order_by(*order_by)
        if joinedloads:
            for jl in joinedloads:
                statement = statement.options(joinedload(jl))
        return statement

    async def list(
            self,
            filters: FilterType | None = None,
            order_by: OrderByType | None = None,
            joinedloads: List[Any] | None = None,
    ) -> List[ModelType]:
        """List records without pagination."""
        statement = self.list_statement(filters, order_by, joinedloads)
        result = await self.session.exec(statement)
        return list(result.all())

    async def list_paginated(
            self,
            pagination: Pagination,
            filters: FilterType | None = None,
            order_by: OrderByType | None = None,
            joinedloads: List[Any] | None = None,
    ) -> PaginationResponse[ModelType]:
        """List records with pagination and return a PaginationResponse envelope."""
        pagination = pagination or Pagination()

        items_stmt = self.list_statement(filters, order_by, joinedloads)
        items_stmt = items_stmt.offset(pagination.offset).limit(pagination.limit)
        items_result = await self.session.exec(items_stmt)
        items = list(items_result.all())

        count_stmt = self.list_statement(filters)
        count_stmt = select(func.count()).select_from(count_stmt.subquery())
        total_result = await self.session.exec(count_stmt)
        total = total_result.one() or 0

        return PaginationResponse.from_items(items, total, pagination.offset, pagination.limit)

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

    async def update_or_raise(
            self,
            record_id: uuid.UUID,
            data: Dict[str, Any]
    ) -> ModelType:
        """
        Update an existing record or raise NotFoundAppException.
        
        Args:
            record_id: The record ID
            data: Dictionary of field values to update
            
        Returns:
            The updated record
            
        Raises:
            NotFoundAppException: If record not found
        """
        record = await self.update(record_id, data)
        if not record:
            raise NotFoundAppException(
                f"{self.model.__name__} with ID {record_id} not found"
            )
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

    async def refresh(self, record: ModelType) -> None:
        """Refresh a record from the database."""
        await self.session.refresh(record)

    # Note: commit() and rollback() are intentionally removed.
    # Transaction management should be handled by the @transactional decorator
    # or the get_session dependency, not by repositories.
