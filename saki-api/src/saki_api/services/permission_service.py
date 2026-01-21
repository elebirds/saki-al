"""
Permission Service - Business logic for Permission operations.
"""
import uuid
from typing import Optional, List

from fastapi import HTTPException

from saki_api.models import RolePermission
from saki_api.repositories.permission_repository import PermissionRepository


class PermissionService:
    """Service for permission business logic."""

    def __init__(self, repo: PermissionRepository):
        self.repo = repo

    async def get_by_id(self, permission_id: uuid.UUID) -> RolePermission:
        """Get permission by ID or raise 404."""
        perm = await self.repo.get_by_id(permission_id)
        if not perm:
            raise HTTPException(status_code=404, detail="Permission not found")
        return perm

    async def get_role_permissions(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a role."""
        return await self.repo.get_role_permissions(role_id)

    async def get_user_permissions(self, user_id: uuid.UUID) -> List[str]:
        """Get all permissions for a user through their roles."""
        return await self.repo.get_user_permissions(user_id)

    async def add_permission(self, role_id: uuid.UUID, permission: str, conditions: Optional[dict] = None) -> RolePermission:
        """
        Add a permission to a role.
        
        Args:
            role_id: Role ID
            permission: Permission string
            conditions: Optional conditions for the permission
        
        Raises:
            HTTPException: If permission already exists for role
        """
        # Check if permission already exists
        if await self.repo.check_permission_exists(role_id, permission):
            raise HTTPException(
                status_code=400,
                detail=f"Permission {permission} already exists for this role"
            )

        perm = await self.repo.create(role_id, permission, conditions)
        await self.repo.commit()
        return perm

    async def update_permission(self, permission_id: uuid.UUID, permission_data: dict) -> RolePermission:
        """Update a permission."""
        perm = await self.repo.update(permission_id, permission_data)
        if not perm:
            raise HTTPException(status_code=404, detail="Permission not found")

        await self.repo.commit()
        return perm

    async def remove_permission(self, permission_id: uuid.UUID) -> bool:
        """Remove a permission."""
        result = await self.repo.delete(permission_id)
        if result:
            await self.repo.commit()
        return result

    async def remove_role_permissions(self, role_id: uuid.UUID) -> int:
        """Remove all permissions from a role. Returns count of deleted permissions."""
        count = await self.repo.delete_by_role(role_id)
        await self.repo.commit()
        return count
