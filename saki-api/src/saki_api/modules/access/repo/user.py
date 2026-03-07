"""
User Repository - Data access layer for User operations.
"""
import uuid
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.domain.access.user import User
from saki_api.schemas import UserRead


class UserRepository(BaseRepository[User]):
    """Repository for User data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        return await self.get_one([User.email == email])

    async def get_by_email_or_raise(self, email: str) -> User:
        return await self.get_one_or_raise([User.email == email])

    async def list_active_paginated(
            self,
            pagination: Pagination = Pagination(),
            q: str | None = None,
    ) -> PaginationResponse[User]:
        """List active users with pagination."""
        filters = [User.is_active == True]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(
                or_(
                    User.email.ilike(pattern),
                    User.full_name.ilike(pattern),
                )
            )
        return await self.list_paginated(pagination=pagination, filters=filters)

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
        total = await self.session.scalar(count_stmt) or 0

        return PaginationResponse.from_items(items, total, pagination.offset, pagination.limit)
