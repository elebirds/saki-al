"""
Permission Service - Business logic for Permission operations.
"""
import uuid
from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import (
    DataAlreadyExistsAppException,
)
from saki_api.db.transaction import transactional
from saki_api.models import RolePermission
from saki_api.repositories.permission_repository import PermissionRepository
from saki_api.schemas import RolePermissionCreate, RolePermissionUpdate
from saki_api.services.base_service import BaseService


class PermissionService(BaseService[RolePermission, PermissionRepository, RolePermissionCreate, RolePermissionUpdate]):
    """Service for permission business logic."""

    def __init__(self, session: AsyncSession):
        super().__init__(RolePermission, PermissionRepository, session)

    async def list_by_role(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a role."""
        return await self.repository.list_by_role(role_id)

    async def get_by_user(self, user_id: uuid.UUID) -> List[str]:
        """Get all permissions for a user through their roles."""
        return await self.repository.get_by_user(user_id)

    @transactional
    async def add(self, role_id: uuid.UUID, permission: str) -> RolePermission:
        """
        Add a permission to a role.
        
        Args:
            role_id: Role ID
            permission: Permission string
        
        Raises:
            HTTPException: If permission already exists for role
        """
        # Check if permission already exists
        if await self.repository.exists(role_id, permission):
            raise DataAlreadyExistsAppException(
                f"Permission {permission} already exists for this role"
            )

        return await self.repository.add(role_id, permission)

    @transactional
    async def update_permission(self, permission_id: uuid.UUID, permission_data: dict) -> RolePermission:
        """Update a permission."""
        return await self.repository.update_or_raise(permission_id, permission_data)

    @transactional
    async def delete_by_role(self, role_id: uuid.UUID) -> int:
        """Delete all permissions from a role. Returns count of deleted permissions."""
        return await self.repository.delete_by_role(role_id)
