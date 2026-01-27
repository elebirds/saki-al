"""
Role Service - Business logic for Role operations.
"""

import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.rbac.audit import (
    log_role_create,
    log_role_update,
    log_role_delete,
)
from saki_api.models import Role, RoleType, User
from saki_api.repositories.role_repository import RoleRepository
from saki_api.schemas import RoleCreate, RoleUpdate, RoleRead, RolePermissionRead
from saki_api.services.base_service import BaseService


class RoleService(BaseService[Role, RoleCreate, RoleUpdate]):
    """Service for role business logic."""

    def __init__(self, session: AsyncSession, current_user: Optional[User] = None):
        super().__init__(Role, session, current_user)
        # Override repository with RoleRepository for additional methods
        self.repo = RoleRepository(session)

    # Keep custom methods that extend BaseService functionality
    async def get_by_name(self, name: str) -> Optional[Role]:
        """Get role by name."""
        return await self.repo.get_by_name(name)

    async def list_roles(self, role_type: Optional[RoleType] = None) -> List[Role]:
        """List all roles, optionally filtered by type."""
        return await self.repo.list_all(role_type=role_type)

    async def get_default_role(self) -> Optional[Role]:
        """Get the default role for new users."""
        return await self.repo.get_default_role()

    async def create_role(self, role_in: RoleCreate) -> Role:
        """
        Create a custom role.
        
        Args:
            role_in: Role creation data
        
        Raises:
            HTTPException: If role name exists or parent role invalid
        """
        # Check name uniqueness
        existing = await self.repo.get_by_name(role_in.name)
        if existing:
            raise HTTPException(status_code=400, detail="Role name already exists")

        # Validate parent role if specified
        if role_in.parent_id:
            parent = await self.repo.get_by_id(role_in.parent_id)
            if not parent:
                raise HTTPException(status_code=400, detail="Parent role not found")
            if parent.type != role_in.type:
                raise HTTPException(
                    status_code=400,
                    detail="Parent role must be of the same type"
                )

        # Create role
        role_data = {
            "name": role_in.name,
            "display_name": role_in.display_name,
            "description": role_in.description,
            "type": role_in.type,
            "parent_id": role_in.parent_id,
            "is_system": False,
            "is_default": False,
        }
        role = await self.repo.create(role_data)

        # Add permissions
        for perm_in in role_in.permissions:
            await self.repo.add_permission(role.id, perm_in.permission, perm_in.conditions)

        # Audit log
        log_role_create(
            session=self.repo.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
                "permissions": [p.permission for p in role_in.permissions],
            },
            actor_id=self.current_user.id,
        )

        await self.repo.commit()
        await self.repo.refresh(role)
        return role

    async def update_role(self, role_id: uuid.UUID, role_in: RoleUpdate) -> Role:
        """
        Update a role.
        
        Args:
            role_id: Role ID to update
            role_in: Update data
        
        Raises:
            HTTPException: If role not found or permission denied
        """
        role = await self.get_by_id(role_id)

        # Store old values for audit
        old_data = {
            "display_name": role.display_name,
            "description": role.description,
        }

        # Update basic fields
        if role_in.display_name is not None:
            role.display_name = role_in.display_name
        if role_in.description is not None:
            role.description = role_in.description
        if role_in.sort_order is not None:
            role.sort_order = role_in.sort_order

        # Update parent (only for non-system roles)
        if role_in.parent_id is not None and not role.is_system:
            if role_in.parent_id:
                parent = await self.repo.get_by_id(role_in.parent_id)
                if not parent:
                    raise HTTPException(status_code=400, detail="Parent role not found")
                if parent.type != role.type:
                    raise HTTPException(
                        status_code=400,
                        detail="Parent role must be of the same type"
                    )
            role.parent_id = role_in.parent_id

        # Update permissions (only for non-system roles)
        if role_in.permissions is not None:
            if role.is_system:
                raise HTTPException(
                    status_code=403,
                    detail="Cannot modify permissions of system preset roles"
                )

            # Clear old permissions and add new ones
            await self.repo.clear_permissions(role_id)
            for perm_in in role_in.permissions:
                await self.repo.add_permission(role.id, perm_in.permission, perm_in.conditions)

        role.updated_at = datetime.utcnow()
        await self.repo.update(role_id, {
            "display_name": role.display_name,
            "description": role.description,
            "sort_order": role.sort_order,
            "parent_id": role.parent_id,
            "updated_at": role.updated_at,
        })

        # Audit log
        log_role_update(
            session=self.repo.session,
            role_id=role.id,
            old_data=old_data,
            new_data={
                "display_name": role.display_name,
                "description": role.description,
            },
            actor_id=self.current_user.id,
        )

        await self.repo.commit()
        await self.repo.refresh(role)
        return role

    async def delete_role(self, role_id: uuid.UUID) -> bool:
        """
        Delete a role.
        
        Args:
            role_id: Role ID to delete
        
        Raises:
            HTTPException: If role not found or is system role
        """
        role = await self.get_by_id(role_id)

        # Prevent deletion of system roles
        if role.is_system:
            raise HTTPException(
                status_code=403,
                detail="System preset roles cannot be deleted"
            )

        # Prevent deletion of default role
        if role.is_default:
            raise HTTPException(
                status_code=403,
                detail="Default role cannot be deleted"
            )

        # Audit log
        log_role_delete(
            session=self.repo.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
            },
            actor_id=self.current_user.id,
        )

        # Delete role and its permissions
        await self.repo.clear_permissions(role_id)

        # Use BaseService delete method
        await self.delete(role_id)
        return True

    async def build_role_read(self, role: Role) -> RoleRead:
        """Build RoleRead response with permissions."""
        perms = await self.repo.get_permissions(role.id)

        return RoleRead(
            id=role.id,
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            type=role.type,
            parent_id=role.parent_id,
            is_system=role.is_system,
            is_default=role.is_default,
            is_super_admin=role.is_super_admin,
            is_admin=role.is_admin,
            sort_order=role.sort_order,
            created_at=role.created_at,
            updated_at=role.updated_at,
            permissions=[
                RolePermissionRead(
                    id=p.id,
                    permission=p.permission,
                    conditions=p.conditions,
                )
                for p in perms
            ],
        )
