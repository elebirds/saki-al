"""
User Repository - Data access layer for User operations.
"""
import uuid
from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.user import User
from saki_api.repositories.base import BaseRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas import UserRead
from saki_api.schemas.pagination import PaginationResponse


class UserRepository(BaseRepository[User]):
    """Repository for User data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        return await self.get_one([User.email == email])

    async def get_by_email_or_raise(self, email: str) -> User:
        return await self.get_one_or_raise([User.email == email])

    async def list_active_paginated(self, pagination: Pagination = Pagination()) -> PaginationResponse[User]:
        """List active users with pagination."""
        return await self.list_paginated(pagination=pagination, filters=[User.is_active == True])

    async def get_with_roles_by_id(self, user_id: uuid.UUID) -> Optional[UserRead]:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.roles))  # type: ignore
            # 预加载所有角色
        )
        result = await self.session.exec(statement)
        return UserRead.model_validate(result.first()) if result else None

    async def list_with_roles_paginated(self, pagination: Pagination) -> PaginationResponse[UserRead]:
        statement = (
            select(User)
            .options(selectinload(User.roles))  # type: ignore
        )

        # Items
        items_stmt = statement.offset(pagination.offset).limit(pagination.limit)
        items_result = await self.session.exec(items_stmt)
        items = [UserRead.model_validate(result) for result in items_result.all()]

        # Total
        count_stmt = select(func.count()).select_from(statement.subquery())
        total_result = await self.session.exec(count_stmt)
        total = total_result.one() or 0

        return PaginationResponse.from_items(items, total, pagination.offset, pagination.limit)
