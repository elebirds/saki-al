"""
Permission Repository - Data access layer for Permission operations.
"""
import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models import RolePermission
from saki_api.repositories.base_repository import BaseRepository


class PermissionRepository(BaseRepository[RolePermission]):
    """Repository for Permission data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(RolePermission, session)

    async def list_by_role(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a specific role."""
        return await self.list(filters=[RolePermission.role_id == role_id])

    async def get_by_user(self, user_id: uuid.UUID) -> List[str]:
        """Get all permissions for a user through their system roles."""
        from saki_api.models import UserSystemRole

        statement = select(RolePermission).join(UserSystemRole).where(UserSystemRole.user_id == user_id)

        result = await self.session.exec(statement)
        perms = result.all()
        return list(set(p.permission for p in perms))

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
