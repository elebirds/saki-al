"""
Base Repository - Generic data access layer for CRUD operations.

Provides generic async CRUD operations for SQLModel models.
"""

import uuid
from typing import TypeVar, Generic, Optional, List, Type, Any, Dict

from sqlalchemy import exists
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.repositories.query import Pagination, FilterType, OrderByType

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
            filters: FilterType = None
    ) -> Optional[ModelType]:
        """
        Get one record.

        Args:
            filters: Optional dictionary of field filters

        Returns:
            List of records
        """
        statement = select(self.model)

        if filters: statement = statement.where(*filters)

        result = await self.session.exec(statement)
        # 使用 .first() 只取一条，即使匹配多条也只返回第一条
        return result.first()

    async def get_one_or_raise(
            self,
            filters: FilterType = None
    ) -> ModelType:
        """
        Get one record or raise NotFoundAppException.
        
        Args:
            filters: Optional dictionary of field filters
            
        Returns:
            The record
            
        Raises:
            NotFoundAppException: If record not found
        """
        record = await self.get_one(filters)
        if not record:
            filter_str = f" with filters {filters}" if filters else ""
            raise NotFoundAppException(
                f"{self.model.__name__}{filter_str} not found"
            )
        return record

    async def list(
            self,
            pagination: Pagination = Pagination(),
            filters: FilterType = None,
            order_by: OrderByType = None,
    ) -> List[ModelType]:
        """
        List records with pagination, filtering, and ordering.
        
        Can be called either with a ListQuery object or with keyword arguments.
        
        Args:
            pagination: Optional Pagination object (defaults to Pagination())
            filters: Optional list of SQLAlchemy where clause expressions
            order_by: Optional list of SQLAlchemy order by expressions
            
        Returns:
            List of records
            
        Examples:
            from sqlalchemy import desc
            from saki_api.models.user import User
            
            # Using keyword arguments (recommended)
            await repo.list(filters=[User.is_active == True])
            await repo.list(pagination=Pagination(skip=10, limit=20))
            await repo.list(
                pagination=Pagination(skip=0, limit=50),
                filters=[User.status == "active", User.age >= 18],
                order_by=[desc(User.created_at)]
            )
        """
        statement = select(self.model)
        if filters: statement = statement.where(*filters)
        if order_by: statement = statement.order_by(*order_by)
        statement = statement.offset(pagination.skip).limit(pagination.limit)
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
