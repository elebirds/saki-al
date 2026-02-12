"""
Permission Query Service - Query user permissions.

Provides separated endpoints for system and resource permissions.
Uses PermissionService which follows the new architecture pattern.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac.enums import ResourceType
from saki_api.repositories import ResourceMemberRepository
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.user_system_role import UserSystemRoleRepository
from saki_api.schemas import RoleReadMinimal
from saki_api.schemas.permission import (
    SystemPermissionsResponse,
    ResourcePermissionsResponse,
)
from saki_api.services.access.permission import PermissionService
from saki_api.services.access.resource_owner import ResourceOwnerService


class PermissionQueryService:
    """
    Service for querying user permissions.
    
    Separates system permissions and resource permissions into different methods.
    Uses PermissionService for permission logic, following repository pattern.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.role_repo = RoleRepository(session)
        self.user_role_repo = UserSystemRoleRepository(session)
        self.resource_member_repo = ResourceMemberRepository(session)
        self.permission_service = PermissionService(session)
        self.permission_repo = self.permission_service.permission_repo
        self.resource_owner_service = ResourceOwnerService(session)

    async def get_system_permissions(self, user_id: uuid.UUID) -> SystemPermissionsResponse:
        """
        Get system-level permissions for a user.
        
        Returns only permissions from system roles, not resource roles.
        
        Args:
            user_id: User ID
            
        Returns:
            SystemPermissionsResponse with system roles and permissions
        """
        # Get user's system roles
        system_roles: List[RoleReadMinimal] = []
        is_super_admin = False
        permissions: set[str] = set()
        for each in await self.user_role_repo.get_system_roles(user_id, datetime.utcnow()):
            system_roles.append(RoleReadMinimal.model_validate(each))
            is_super_admin |= each.is_super_admin
            permissions.update(await self.permission_service.get_role_permissions(each.id))

        return SystemPermissionsResponse(
            user_id=user_id,
            system_roles=system_roles,
            permissions=list(permissions),
            is_super_admin=is_super_admin,
        )

    async def get_resource_permissions(
            self,
            user_id: uuid.UUID,
            resource_type: str,
            resource_id: uuid.UUID,
    ) -> ResourcePermissionsResponse:
        """
        Get resource-specific permissions for a user.
        
        Returns only permissions from resource roles, not system roles.
        Also includes resource role and owner status.
        
        Args:
            user_id: User ID
            resource_type: Resource type (e.g., "dataset")
            resource_id: Resource ID
            
        Returns:
            ResourcePermissionsResponse with resource role, permissions, and owner status
        """
        # Convert resource_type string to enum
        try:
            rt = ResourceType(resource_type)
        except ValueError:
            # Invalid resource type, return empty permissions
            return ResourcePermissionsResponse(
                resource_role=None,
                permissions=[],
                is_owner=False,
            )

        # Get resource role using permission service
        member = await self.resource_member_repo.get_by_user_and_resource(user_id, rt, resource_id)
        resource_role: Optional[RoleReadMinimal] = None
        if member:
            role = await self.role_repo.get_by_id(member.role_id)
            if role:
                resource_role = RoleReadMinimal.model_validate(role)

        # Get resource permissions only - use repository directly with ResourceType enum
        resource_permissions = await self.permission_repo.get_user_resource_permissions(
            user_id, rt, resource_id
        )

        # Check if user is owner
        is_owner = await self.resource_owner_service.is_owner(rt, resource_id, user_id)

        return ResourcePermissionsResponse(
            resource_role=resource_role,
            permissions=list(resource_permissions),
            is_owner=is_owner,
        )
