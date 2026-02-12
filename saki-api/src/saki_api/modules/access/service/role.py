"""
Role Service - Business logic for Role operations.
"""

import uuid
from typing import Optional

from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from typing_extensions import override

from saki_api.core.exceptions import (
    BadRequestAppException,
    ForbiddenAppException,
    DataAlreadyExistsAppException,
)
from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.infra.db.transaction import transactional
from saki_api.modules.access.domain.rbac.enums import Permissions
from saki_api.modules.access.domain.rbac.permission import parse_permission
from saki_api.modules.access.domain.rbac.resource_member import ResourceMember
from saki_api.modules.access.domain.rbac.role import Role, RoleType
from saki_api.modules.access.domain.rbac.user_system_role import UserSystemRole
from saki_api.modules.access.repo.permission import PermissionRepository
from saki_api.modules.access.repo.role import RoleRepository
from saki_api.modules.access.service.audit import (
    log_role_create,
    log_role_update,
    log_role_delete,
)
from saki_api.modules.shared.application.crud_service import CrudServiceBase
from saki_api.schemas import RoleCreate, RoleUpdate, RoleRead, RolePermissionRead


class RoleService(CrudServiceBase[Role, RoleRepository, RoleCreate, RoleUpdate]):
    """Service for role business logic."""

    def __init__(self, session: AsyncSession):
        super().__init__(Role, RoleRepository, session)
        self.permission_repo = PermissionRepository(session)

    @staticmethod
    def _allowed_permission_values() -> set[str]:
        values: set[str] = set()
        for key, value in vars(Permissions).items():
            if key.startswith("_") or not isinstance(value, str) or ":" not in value:
                continue
            try:
                parse_permission(value)
            except ValueError:
                continue
            values.add(value)
        return values

    @classmethod
    def _split_role_type_permissions(cls) -> tuple[list[str], list[str], list[str]]:
        all_permissions = sorted(cls._allowed_permission_values())
        system_permissions = [p for p in all_permissions if p.endswith(":all")]
        resource_permissions = [
            p for p in all_permissions if p.endswith(":assigned") or p.endswith(":self")
        ]
        return all_permissions, system_permissions, resource_permissions

    @classmethod
    def _validate_permission_list(
            cls,
            permissions: list[str],
            *,
            role_type: RoleType,
    ) -> None:
        allowed = cls._allowed_permission_values()
        invalid = sorted({item for item in permissions if item not in allowed})
        if invalid:
            raise BadRequestAppException(
                "unknown permission(s): " + ", ".join(invalid)
            )

        if role_type == RoleType.SYSTEM:
            disallowed = [item for item in permissions if not item.endswith(":all")]
            if disallowed:
                raise BadRequestAppException(
                    "system role only accepts ':all' permissions"
                )
        if role_type == RoleType.RESOURCE:
            disallowed = [
                item
                for item in permissions
                if not (item.endswith(":assigned") or item.endswith(":self"))
            ]
            if disallowed:
                raise BadRequestAppException(
                    "resource role only accepts ':assigned' or ':self' permissions"
                )

    async def get_permission_catalog(self) -> dict[str, list[str]]:
        all_permissions, system_permissions, resource_permissions = self._split_role_type_permissions()
        return {
            "all_permissions": all_permissions,
            "system_permissions": system_permissions,
            "resource_permissions": resource_permissions,
        }

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
    ) -> PaginationResponse[RoleRead]:
        """List roles with pagination, optionally filtered by type."""
        roles = await self.repository.list_paginated(
            filters=[Role.type == role_type] if role_type else None,
            pagination=pagination,
            order_by=[
                Role.sort_order,
                Role.created_at,
            ]
        )
        return await roles.map_async(self.build_role_read)

    @transactional
    @override
    async def create(self, role_in: RoleCreate) -> Role:
        """
        Create a custom role.
        
        Args:
            role_in: Role creation data
        """
        # Check name uniqueness
        existing = await self.repository.get_by_name(role_in.name)
        if existing:
            raise DataAlreadyExistsAppException("Role name already exists")

        permission_values = [p.permission for p in role_in.permissions]
        self._validate_permission_list(permission_values, role_type=role_in.type)

        # Create role - use model_dump to convert schema to dict, excluding permissions
        role = await self.repository.create(role_in.model_dump(exclude={"permissions"}))

        # Add permissions
        for perm_in in role_in.permissions:
            await self.permission_repo.add(role.id, perm_in.permission)

        # Audit log
        await log_role_create(
            session=self.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
                "permissions": [p.permission for p in role_in.permissions],
            }
        )
        return role

    @transactional
    @override
    async def update(
            self,
            role_id: uuid.UUID,
            role_in: RoleUpdate,
    ) -> Role:
        """
        Update a role.
        
        Args:
            role_id: Role ID to update
            role_in: Update data
        
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
            permission_values = [p.permission for p in role_in.permissions]
            self._validate_permission_list(permission_values, role_type=role.type)
            await self.permission_repo.delete_by_role(role_id)
            for perm_in in role_in.permissions:
                await self.permission_repo.add(role.id, perm_in.permission)

        updated_role = await self.repository.update_or_raise(role_id, update_data)

        await log_role_update(
            session=self.session,
            role_id=updated_role.id,
            old_data=old_data,
            new_data={
                "display_name": updated_role.display_name,
                "description": updated_role.description,
            }
        )

        return updated_role

    @transactional
    @override
    async def delete(self, role_id: uuid.UUID) -> Role:
        """
        Delete a role.
        
        Args:
            role_id: Role ID to delete
        
        Raises:
            HTTPException: If role not found or is system role
        """
        role = await self.get_by_id_or_raise(role_id)

        # Prevent deletion of system roles
        if role.is_system: raise ForbiddenAppException("System preset roles cannot be deleted")

        # Prevent deletion of default role
        if role.is_default: raise ForbiddenAppException("Default role cannot be deleted")

        user_assignment_count = (
            await self.session.exec(
                select(func.count()).select_from(UserSystemRole).where(UserSystemRole.role_id == role_id)
            )
        ).one() or 0
        resource_assignment_count = (
            await self.session.exec(
                select(func.count()).select_from(ResourceMember).where(ResourceMember.role_id == role_id)
            )
        ).one() or 0
        if user_assignment_count or resource_assignment_count:
            raise BadRequestAppException(
                "Role is still in use and cannot be deleted"
            )

        # Audit log
        await log_role_delete(
            session=self.session,
            role_id=role.id,
            role_data={
                "name": role.name,
                "display_name": role.display_name,
                "type": role.type.value,
            }
        )

        # Delete role and its permissions
        await self.permission_repo.delete_by_role(role_id)

        # Use BaseService delete method
        return await super().delete(role_id)

    async def build_role_read(self, role: Role) -> RoleRead:
        """Build RoleRead response with permissions."""
        perms = await self.permission_repo.list_by_role(role.id)

        result = RoleRead.model_validate(role.model_dump(exclude={"permissions"}))
        result.permissions = [RolePermissionRead.model_validate(p) for p in perms]
        return result
