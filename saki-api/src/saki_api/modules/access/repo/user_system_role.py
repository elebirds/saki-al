"""
User System Role Repository - Data access layer for User-(Sys)Role association operations.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.api.user_system_role import UserSystemRoleCreate, UserSystemRoleRead
from saki_api.modules.access.domain.rbac.role import Role
from saki_api.modules.access.domain.rbac.user_system_role import UserSystemRole
from saki_api.modules.shared.modeling import RoleType


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

    async def get_by_user_with_roles(self, user_id: uuid.UUID) -> List[UserSystemRoleRead]:
        statement = (
            select(UserSystemRole, Role)
            .join(Role)  # Implicit join based on foreign key
            .where(UserSystemRole.user_id == user_id)
            .where(Role.type == RoleType.SYSTEM)
        )
        result = await self.session.exec(statement)
        res: List[UserSystemRoleRead] = []
        for user_role, role in result:
            # Use model_validate to convert model to schema, then add role details
            role_read = UserSystemRoleRead.model_validate(user_role)
            role_read.role_name = role.name
            role_read.role_display_name = role.display_name
            res.append(role_read)
        return res

    async def get_active_role_ids(self, user_id: uuid.UUID, now: Optional[datetime] = None) -> List[uuid.UUID]:
        """
        Get all active system role IDs for a user.
        
        Args:
            user_id: User ID
            now: Date to filter expired roles. If None, uses current time.
            
        Returns:
            List of active role IDs
        """
        if now is None:
            now = datetime.utcnow()
        user_roles = await self.list(filters=[
            UserSystemRole.user_id == user_id,
            (UserSystemRole.expires_at == None) | (UserSystemRole.expires_at > now)
        ])
        return [ur.role_id for ur in user_roles]

    async def has_super_admin_role(self, user_id: uuid.UUID, now: Optional[datetime] = None) -> bool:
        """
        Efficiently check if user has super admin role using SQL JOIN.
        
        This is much more efficient than fetching all roles and checking individually.
        
        Args:
            user_id: User ID
            now: Date to filter expired roles. If None, uses current time.
            
        Returns:
            True if user has super admin role, False otherwise
        """
        if now is None:
            now = datetime.utcnow()

        # Use EXISTS query for maximum efficiency - stops at first match
        from sqlalchemy import exists
        subquery = (
            select(1)
            .select_from(UserSystemRole)
            .join(Role)
            .where(
                UserSystemRole.user_id == user_id,
                Role.is_super_admin == True,
                Role.type == RoleType.SYSTEM,
                (UserSystemRole.expires_at == None) | (UserSystemRole.expires_at > now)
            )
        )
        statement = select(exists(subquery))
        result = await self.session.exec(statement)
        return result.first() or False

    async def has_admin_role(self, user_id: uuid.UUID, now: Optional[datetime] = None) -> bool:
        """
        Efficiently check if user has admin role (including super admin) using SQL JOIN.
        
        This is much more efficient than fetching all roles and checking individually.
        
        Args:
            user_id: User ID
            now: Date to filter expired roles. If None, uses current time.
            
        Returns:
            True if user has admin or super admin role, False otherwise
        """
        if now is None:
            now = datetime.utcnow()

        # Use EXISTS query for maximum efficiency - stops at first match
        from sqlalchemy import exists
        subquery = (
            select(1)
            .select_from(UserSystemRole)
            .join(Role)
            .where(
                UserSystemRole.user_id == user_id,
                (Role.is_admin == True) | (Role.is_super_admin == True),
                Role.type == RoleType.SYSTEM,
                (UserSystemRole.expires_at == None) | (UserSystemRole.expires_at > now)
            )
        )
        statement = select(exists(subquery))
        result = await self.session.exec(statement)
        return result.first() or False
