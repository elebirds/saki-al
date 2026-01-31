"""
Permission Query Service - Query user permissions.

Provides separated endpoints for system and resource permissions.
Uses PermissionService which follows the new architecture pattern.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac.enums import ResourceType, RoleType
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_system_role_repository import UserSystemRoleRepository
from saki_api.services.permission_service import PermissionService
from saki_api.services.resource_owner_service import ResourceOwnerService
from saki_api.schemas.permission import (
    SystemPermissionsResponse,
    ResourcePermissionsResponse,
    RoleInfo,
)


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
        self.permission_service = PermissionService(session)
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
        # Get user's system roles (filter out expired)
        user_roles = await self.user_role_repo.get_by_user(user_id)
        system_roles: List[RoleInfo] = []
        
        for ur in user_roles:
            # Filter out expired roles
            if ur.expires_at and ur.expires_at < datetime.utcnow():
                continue
                
            role = await self.role_repo.get_by_id(ur.role_id)
            if role and role.type == RoleType.SYSTEM:  # Only system roles
                system_roles.append(RoleInfo(
                    id=role.id,
                    name=role.name,
                    displayName=role.display_name,
                ))
        
        # Check if super admin
        is_super_admin = await self.permission_service.is_super_admin(user_id)
        
        # Get system permissions only
        permissions = await self.permission_service.get_user_system_permissions(user_id)
        
        return SystemPermissionsResponse(
            userId=user_id,
            systemRoles=system_roles,
            permissions=list(permissions),
            isSuperAdmin=is_super_admin,
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
                resourceRole=None,
                permissions=[],
                isOwner=False,
            )
        
        # Get resource role using permission service
        role = await self.permission_service.get_user_role_in_resource(user_id, rt, resource_id)
        resource_role: Optional[RoleInfo] = None
        if role:
            resource_role = RoleInfo(
                id=role.id,
                name=role.name,
                displayName=role.display_name,
            )
        
        # Get resource permissions only
        resource_permissions = await self.permission_service.get_user_resource_permissions(
            user_id, rt, resource_id
        )
        
        # Check if user is owner
        is_owner = await self.resource_owner_service.is_owner(rt, resource_id, user_id)
        
        return ResourcePermissionsResponse(
            resourceRole=resource_role,
            permissions=list(resource_permissions),
            isOwner=is_owner,
        )
