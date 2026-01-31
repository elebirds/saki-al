"""
Permission Service - Business logic for permission queries.

Provides permission querying functionality using repositories instead of direct session access.
"""

import uuid
from datetime import datetime
from typing import Set, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac.enums import ResourceType, RoleType
from saki_api.models.rbac.role import Role
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.permission_repository import PermissionRepository
from saki_api.repositories.user_system_role_repository import UserSystemRoleRepository
from saki_api.repositories.resource_member_repository import ResourceMemberRepository


class PermissionService:
    """
    Service for querying permissions.
    
    Uses repositories for data access, following the new architecture pattern.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.role_repo = RoleRepository(session)
        self.permission_repo = PermissionRepository(session)
        self.user_role_repo = UserSystemRoleRepository(session)
        self.resource_member_repo = ResourceMemberRepository(session)
    
    async def get_role_permissions(self, role_id: uuid.UUID) -> Set[str]:
        """
        Get all permissions for a role.
        
        Currently returns direct permissions only. Role inheritance can be added later.
        
        Args:
            role_id: Role ID
            
        Returns:
            Set of permission strings
        """
        role_perms = await self.permission_repo.list_by_role(role_id)
        return {rp.permission for rp in role_perms}
    
    async def get_user_system_permissions(self, user_id: uuid.UUID) -> Set[str]:
        """
        Get all system-level permissions for a user.
        
        Combines permissions from all assigned system roles (excluding expired).
        
        Args:
            user_id: User ID
            
        Returns:
            Set of permission strings
        """
        permissions: Set[str] = set()
        
        # Get user's system roles
        user_roles = await self.user_role_repo.get_by_user(user_id)
        
        for ur in user_roles:
            # Filter out expired roles
            if ur.expires_at and ur.expires_at < datetime.utcnow():
                continue
            
            # Verify it's a system role
            role = await self.role_repo.get_by_id(ur.role_id)
            if role and role.type == RoleType.SYSTEM:
                role_perms = await self.get_role_permissions(role.id)
                permissions.update(role_perms)
        
        return permissions
    
    async def get_user_resource_permissions(
        self,
        user_id: uuid.UUID,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
    ) -> Set[str]:
        """
        Get permissions for a user on a specific resource.
        
        Args:
            user_id: User ID
            resource_type: Resource type enum
            resource_id: Resource ID
            
        Returns:
            Set of permission strings
        """
        permissions: Set[str] = set()
        
        # Get user's membership in the resource
        member = await self.resource_member_repo.get_by_user_and_resource(
            user_id, resource_type, resource_id
        )
        
        if member:
            role_perms = await self.get_role_permissions(member.role_id)
            permissions.update(role_perms)
        
        return permissions
    
    async def is_super_admin(self, user_id: uuid.UUID) -> bool:
        """
        Check if user is a super admin by checking if they have super_admin role.
        
        Args:
            user_id: User ID
            
        Returns:
            True if user is super admin, False otherwise
        """
        user_roles = await self.user_role_repo.get_by_user(user_id)
        
        for ur in user_roles:
            # Filter out expired roles
            if ur.expires_at and ur.expires_at < datetime.utcnow():
                continue
            
            role = await self.role_repo.get_by_id(ur.role_id)
            if role and role.is_super_admin:
                return True
        
        return False
    
    async def get_user_role_in_resource(
        self,
        user_id: uuid.UUID,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
    ) -> Optional[Role]:
        """
        Get user's role in a specific resource.
        
        Args:
            user_id: User ID
            resource_type: Resource type enum
            resource_id: Resource ID
            
        Returns:
            Role if user is a member, None otherwise
        """
        member = await self.resource_member_repo.get_by_user_and_resource(
            user_id, resource_type, resource_id
        )
        
        if member:
            return await self.role_repo.get_by_id(member.role_id)
        
        return None
