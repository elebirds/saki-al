"""
User Repository - Data access layer for User operations.
"""
import uuid
from typing import Optional, List

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.user import User
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas import UserRead


class UserRepository(BaseRepository[User]):
    """Repository for User data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        return await self.get_one([User.email == email])

    async def get_by_email_or_raise(self, email: str) -> User:
        return await self.get_one_or_raise([User.email == email])

    async def list_active(self, pagination: Pagination = Pagination()) -> List[User]:
        """List active users with pagination."""
        return await self.list(pagination=pagination, filters=[User.is_active == True])

    async def get_with_roles_by_id(self, user_id: uuid.UUID) -> Optional[UserRead]:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.roles))  # type: ignore
            # 预加载所有角色
        )
        result = await self.session.exec(statement)
        return UserRead.model_validate(result.first()) if result else None

    async def list_with_roles(self, pagination: Pagination) -> List[UserRead]:
        statement = (
            select(User)
            .options(selectinload(User.roles))  # type: ignore
            # 预加载所有角色
        )
        statement = statement.offset(pagination.offset).limit(pagination.limit)
        result = await self.session.exec(statement)
        return [UserRead.model_validate(result) for result in result.all()]
