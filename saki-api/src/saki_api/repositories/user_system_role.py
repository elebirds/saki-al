"""
User System Role Repository - Data access layer for User-(Sys)Role association operations.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.models import RoleType
from saki_api.models.rbac.user_system_role import UserSystemRole
from saki_api.models.rbac.role import Role
from saki_api.repositories.base import BaseRepository
from saki_api.schemas.user_system_role import UserSystemRoleCreate


class UserSystemRoleRepository(BaseRepository[UserSystemRole]):
    def __init__(self, session: AsyncSession):
        super().__init__(UserSystemRole, session)

    async def get_by_user(self, user_id: uuid.UUID) -> List[UserSystemRole]:
        """Get all system role assignments for a user."""
        return await self.list(filters=[UserSystemRole.user_id == user_id])

    async def get_by_user_and_role(
        self,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> Optional[UserSystemRole]:
        """Get a specific user-role association."""
        return await self.get_one([
            UserSystemRole.user_id == user_id,
            UserSystemRole.role_id == role_id,
        ])

    async def get_by_user_and_role_or_raise(
        self,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> UserSystemRole:
        """Get a specific user-role association or raise NotFoundAppException."""
        user_role = await self.get_by_user_and_role(user_id, role_id)
        if not user_role:
            raise NotFoundAppException(
                f"Role {role_id} not assigned to user {user_id}"
            )
        return user_role

    async def assign(
        self,
        role_in: UserSystemRoleCreate,
    ) -> UserSystemRole:
        """
        Assign a system role to a user.
        
        Audit fields (created_by, updated_by) are automatically populated
        by event listeners from the current user context.
        
        Args:
            role_in: UserSystemRoleCreate schema with user_id, role_id, and optional expires_at
            
        Returns:
            Created UserSystemRole association
        """
        return await self.create(role_in.model_dump(exclude_unset=True))

    async def revoke(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        """
        Revoke a system role from a user.
        
        Args:
            user_id: User ID
            role_id: Role ID to revoke
            
        Returns:
            True if revoked, False if not found
        """
        user_role = await self.get_by_user_and_role(user_id, role_id)
        if not user_role:
            return False
        
        return await self.delete(user_role.id)

    async def get_system_roles(self, user_id: uuid.UUID, now: Optional[datetime] = None) -> List[Role]:
        """
        Get all system roles assigned to a user (Role objects).
        
        This method performs a join query to get Role objects directly.
        For UserSystemRole objects, use get_user_system_roles instead.
        
        Args:
            user_id: User ID
            now: Date to filter expired roles. If provided, only returns roles that haven't expired.
            
        Returns:
            List of Role objects assigned to the user
        """
        statement = (
            select(Role)
            .join(UserSystemRole)
            .where(UserSystemRole.user_id == user_id)
            .where(Role.type == RoleType.SYSTEM)
        )
        if now is not None:
            statement = statement.where(
                (UserSystemRole.expires_at == None) |
                (UserSystemRole.expires_at > now)
            )
        result = await self.session.exec(statement)
        return list(result.all())
