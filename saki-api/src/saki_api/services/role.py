"""
Role Service - Business logic for Role operations.
"""

import uuid
from typing import Optional, List

from typing_extensions import override
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import (
    BadRequestAppException,
    ForbiddenAppException,
    DataAlreadyExistsAppException,
)
from saki_api.core.rbac.audit import (
    log_role_create,
    log_role_update,
    log_role_delete,
)
from saki_api.db.transaction import transactional
from saki_api.models.rbac.role import Role, RoleType
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.permission import PermissionRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas import RoleCreate, RoleUpdate, RoleRead, RolePermissionRead
from saki_api.services.base import BaseService


class RoleService(BaseService[Role, RoleRepository, RoleCreate, RoleUpdate]):
    """Service for role business logic."""

    def __init__(self, session: AsyncSession):
        super().__init__(Role, RoleRepository, session)
        self.permission_repo = PermissionRepository(session)

    async def get_default(self) -> Role:
        """Get the default role for new users."""
        return await self.repository.get_default()

    async def get_super_admin(self) -> Role:
        """Get the super admin role for system init."""
        return await self.repository.get_super_admin()

    async def get_by_name(self, name: str) -> Optional[Role]:
        """Get role by name."""
        return await self.repository.get_by_name(name)

    async def list_by_type(
        self,
        role_type: Optional[RoleType] = None,
        pagination: Pagination = Pagination(),
    ) -> List[Role]:
        """List all roles, optionally filtered by type."""
        return await self.repository.list(
            filters=[Role.type == role_type],
            pagination=pagination,
            order_by=[
                Role.sort_order,
                Role.created_at,
            ]
        )

    async def get_default(self) -> Role:
        """Get the default role for new users."""
        return await self.repository.get_default()

    @transactional
    @override
    async def create(self, role_in: RoleCreate, current_user_id: uuid.UUID) -> Role:
        """
        Create a custom role.
        
        Args:
            role_in: Role creation data
            current_user_id: ID of the current user performing the action
        """
        # Check name uniqueness
        existing = await self.repository.get_by_name(role_in.name)
        if existing:
            raise DataAlreadyExistsAppException("Role name already exists")

        # Create role - use model_dump to convert schema to dict, excluding permissions
        role = await self.repository.create(role_in.model_dump(exclude={"permissions"}))

        # Add permissions
        for perm_in in role_in.permissions:
            await self.permission_repo.add(role.id, perm_in.permission)

        # Audit log
        log_role_create(
            session=self.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
                "permissions": [p.permission for p in role_in.permissions],
            },
            actor_id=current_user_id,
        )

        return role

    @transactional
    @override
    async def update(
        self,
        role_id: uuid.UUID,
        role_in: RoleUpdate,
        current_user_id: uuid.UUID,
    ) -> Role:
        """
        Update a role.
        
        Args:
            role_id: Role ID to update
            role_in: Update data
            current_user_id: ID of the current user performing the action
        
        Raises:
            HTTPException: If role not found or permission denied
        """
        role = await self.get_by_id_or_raise(role_id)

        if role.is_system:
            raise ForbiddenAppException("System preset roles cannot be updated")

        # Store old values for audit
        old_data = {
            "display_name": role.display_name,
            "description": role.description,
        }

        # Get update data from schema, excluding permissions (handled separately)
        update_data = role_in.model_dump(exclude_unset=True, exclude={"permissions"})

        # Update permissions (only for non-system roles)
        if role_in.permissions is not None:
            await self.permission_repo.delete_by_role(role_id)
            for perm_in in role_in.permissions:
                await self.permission_repo.add(role.id, perm_in.permission)

        updated_role = await self.repository.update_or_raise(role_id, update_data)

        log_role_update(
            session=self.session,
            role_id=updated_role.id,
            old_data=old_data,
            new_data={
                "display_name": updated_role.display_name,
                "description": updated_role.description,
            },
            actor_id=current_user_id,
        )

        return updated_role

    @transactional
    @override
    async def delete(self, role_id: uuid.UUID, current_user_id: uuid.UUID) -> Role:
        """
        Delete a role.
        
        Args:
            role_id: Role ID to delete
            current_user_id: ID of the current user performing the action
        
        Raises:
            HTTPException: If role not found or is system role
        """
        role = await self.get_by_id_or_raise(role_id)

        # Prevent deletion of system roles
        if role.is_system: raise ForbiddenAppException("System preset roles cannot be deleted")

        # Prevent deletion of default role
        if role.is_default: raise ForbiddenAppException("Default role cannot be deleted")

        # TODO: 如果有用户有这个角色？

        # Audit log
        log_role_delete(
            session=self.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
            },
            actor_id=current_user_id,
        )

        # Delete role and its permissions
        await self.permission_repo.delete_by_role(role_id)

        # Use BaseService delete method
        return await super().delete(role_id)

    async def build_role_read(self, role: Role) -> RoleRead:
        """Build RoleRead response with permissions."""
        perms = await self.permission_repo.list_by_role(role.id)

        result = RoleRead.model_validate(role)
        result.permissions = [RolePermissionRead.model_validate(p) for p in perms]
        return result
