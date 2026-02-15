"""
Permission Repository - Data access layer for Permission operations.
"""
import uuid
from datetime import datetime
from typing import List, Set, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.domain.rbac import RolePermission


class PermissionRepository(BaseRepository[RolePermission]):
    """Repository for Permission data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(RolePermission, session)

    async def list_by_role(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a specific role."""
        return await self.list(filters=[RolePermission.role_id == role_id])

    async def get_permissions_by_role(self, role_id: uuid.UUID) -> Set[str]:
        """Get all permission strings for a specific role."""
        perms = await self.list_by_role(role_id)
        return {p.permission for p in perms}

    async def get_permissions_by_roles(self, role_ids: List[uuid.UUID]) -> Set[str]:
        """Get all permission strings for multiple roles (batch query)."""
        if not role_ids:
            return set()
        statement = select(RolePermission).where(RolePermission.role_id.in_(role_ids))
        result = await self.session.exec(statement)
        perms = result.all()
        return {p.permission for p in perms}

    async def get_by_user(self, user_id: uuid.UUID) -> List[str]:
        """Get all permissions for a user through their system roles."""
        from saki_api.modules.access.domain.rbac import UserSystemRole

        statement = select(RolePermission).join(UserSystemRole).where(UserSystemRole.user_id == user_id)

        result = await self.session.exec(statement)
        perms = result.all()
        return list(set(p.permission for p in perms))

    async def get_user_system_permissions(
            self,
            user_id: uuid.UUID,
            now: Optional[datetime] = None
    ) -> Set[str]:
        """
        Efficiently get all system-level permissions for a user using SQL JOIN.
        
        This method uses a single SQL query with JOIN to get all permissions
        from active system roles, avoiding the need to first fetch role IDs.
        
        Args:
            user_id: User ID
            now: Date to filter expired roles. If None, uses current time.
            
        Returns:
            Set of permission strings
        """
        from datetime import datetime
        from saki_api.modules.access.domain.rbac import UserSystemRole, Role
        from saki_api.modules.access.domain.rbac import RoleType

        if now is None:
            now = datetime.utcnow()

        # Single SQL query with JOIN to get all permissions from active roles
        statement = (
            select(RolePermission.permission)
            .join(UserSystemRole, RolePermission.role_id == UserSystemRole.role_id)
            .join(Role, UserSystemRole.role_id == Role.id)
            .where(
                UserSystemRole.user_id == user_id,
                Role.type == RoleType.SYSTEM,
                (UserSystemRole.expires_at == None) | (UserSystemRole.expires_at > now)
            )
            .distinct()
        )
        result = await self.session.exec(statement)
        return set(result.all())

    async def get_user_resource_permissions(
            self,
            user_id: uuid.UUID,
            resource_type: "ResourceType",
            resource_id: uuid.UUID,
    ) -> Set[str]:
        """
        Efficiently get permissions for a user on a specific resource using SQL JOIN.
        
        This method uses a single SQL query with JOIN to get permissions from the
        user's role in the resource, avoiding multiple queries.
        
        Args:
            user_id: User ID
            resource_type: Resource type enum
            resource_id: Resource ID
            
        Returns:
            Set of permission strings
        """
        from saki_api.modules.access.domain.rbac import ResourceMember

        # Single SQL query with JOIN to get permissions from resource role
        statement = (
            select(RolePermission.permission)
            .join(ResourceMember, RolePermission.role_id == ResourceMember.role_id)
            .where(
                ResourceMember.user_id == user_id,
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id
            )
            .distinct()
        )
        result = await self.session.exec(statement)
        return set(result.all())

    async def add(self, role_id: uuid.UUID, permission: str) -> RolePermission:
        """Create a new permission for a role."""
        data = {
            "role_id": role_id,
            "permission": permission,
        }
        return await self.create(data)

    async def delete_by_role(self, role_id: uuid.UUID) -> int:
        """Delete all permissions for a role. Returns count of deleted permissions."""
        perms = await self.list_by_role(role_id)
        count = len(perms)
        for perm in perms:
            await self.delete(perm.id)
        return count

    async def exists(self, role_id: uuid.UUID, permission: str) -> bool:
        """Check if a specific permission exists for a role."""
        perm = await self.get_one([
            RolePermission.role_id == role_id,
            RolePermission.permission == permission
        ])
        return perm is not None
