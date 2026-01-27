"""
User Repository - Data access layer for User operations.
"""

import uuid
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models import User, UserSystemRole
from saki_api.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        statement = select(User).where(User.email == email)
        return (await self.session.exec(statement)).first()

    async def list_active(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List active users with pagination."""
        result = await self.session.exec(
            select(User).where(User.is_active == True).offset(skip).limit(limit)
        )
        return result.all()

    async def get_system_roles(self, user_id: uuid.UUID) -> List:
        """Get all system roles assigned to a user."""
        from saki_api.models import Role
        statement = select(Role).join(
            UserSystemRole, Role.id == UserSystemRole.role_id
        ).where(UserSystemRole.user_id == user_id)
        result = await self.session.exec(statement)
        return result.all()

    async def get_user_system_roles(self, user_id: uuid.UUID) -> List[UserSystemRole]:
        """Get user system role associations."""
        statement = select(UserSystemRole).where(UserSystemRole.user_id == user_id)
        result = await self.session.exec(statement)
        return result.all()

    async def assign_system_role(self, user_id: uuid.UUID, role_id: uuid.UUID,
                                 assigned_by: uuid.UUID) -> UserSystemRole:
        """Assign a system role to a user."""
        user_role = UserSystemRole(
            user_id=user_id,
            role_id=role_id,
            assigned_by=assigned_by,
        )
        self.session.add(user_role)
        await self.session.flush()
        return user_role

    async def revoke_system_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        """Revoke a system role from a user."""
        statement = select(UserSystemRole).where(
            UserSystemRole.user_id == user_id,
            UserSystemRole.role_id == role_id
        )
        result = await self.session.exec(statement)
        user_role = result.first()
        if not user_role:
            return False

        await self.session.delete(user_role)
        await self.session.flush()
        return True

    async def get_all_user_roles(self, user_id: uuid.UUID) -> List[UserSystemRole]:
        """Get all role assignments for a user."""
        statement = select(UserSystemRole).where(UserSystemRole.user_id == user_id)
        result = await self.session.exec(statement)
        return result.all()

    async def commit(self) -> None:
        """Commit transaction."""
        await self.session.commit()

    async def refresh(self, obj) -> None:
        """Refresh an object."""
        await self.session.refresh(obj)
