"""
Permission Repository - Data access layer for Permission operations.
"""
import uuid
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models import RolePermission


class PermissionRepository:
    """Repository for Permission data access."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, permission_id: uuid.UUID) -> Optional[RolePermission]:
        """Get permission by ID."""
        return await self.session.get(RolePermission, permission_id)

    async def get_role_permissions(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a specific role."""
        statement = select(RolePermission).where(RolePermission.role_id == role_id)
        result = await self.session.exec(statement)
        return result.all()

    async def get_user_permissions(self, user_id: uuid.UUID) -> List[str]:
        """Get all permissions for a user through their roles."""
        from saki_api.models import UserSystemRole

        statement = select(RolePermission).join(
            UserSystemRole,
            UserSystemRole.role_id == RolePermission.role_id
        ).where(UserSystemRole.user_id == user_id)

        result = await self.session.exec(statement)
        perms = result.all()
        return list(set(p.permission for p in perms))

    async def create(self, role_id: uuid.UUID, permission: str, conditions: Optional[dict] = None) -> RolePermission:
        """Create a new permission for a role."""
        perm = RolePermission(
            role_id=role_id,
            permission=permission,
            conditions=conditions,
        )
        self.session.add(perm)
        await self.session.flush()
        return perm

    async def update(self, permission_id: uuid.UUID, permission_data: dict) -> Optional[RolePermission]:
        """Update an existing permission."""
        perm = await self.get_by_id(permission_id)
        if not perm:
            return None

        for key, value in permission_data.items():
            setattr(perm, key, value)

        self.session.add(perm)
        await self.session.flush()
        return perm

    async def delete(self, permission_id: uuid.UUID) -> bool:
        """Delete a permission."""
        perm = await self.get_by_id(permission_id)
        if not perm:
            return False

        await self.session.delete(perm)
        await self.session.flush()
        return True

    async def delete_by_role(self, role_id: uuid.UUID) -> int:
        """Delete all permissions for a role. Returns count of deleted permissions."""
        perms = await self.get_role_permissions(role_id)
        for perm in perms:
            await self.session.delete(perm)
        await self.session.flush()
        return len(perms)

    async def check_permission_exists(self, role_id: uuid.UUID, permission: str) -> bool:
        """Check if a specific permission exists for a role."""
        statement = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission == permission
        )
        return (await self.session.exec(statement)).first() is not None

    async def commit(self) -> None:
        """Commit transaction."""
        await self.session.commit()
