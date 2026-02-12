"""
Resource Member Repository - Data access layer for ResourceMember operations.
"""

import uuid
from typing import List, Optional, Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.infra.db.transaction import transactional
from saki_api.modules.access.domain.rbac.enums import ResourceType
from saki_api.modules.access.domain.rbac.permission import Permission, parse_permission
from saki_api.modules.access.domain.rbac.resource_member import ResourceMember
from saki_api.modules.access.domain.rbac.role import Role
from saki_api.modules.shared.modeling import RolePermission


class ResourceMemberRepository(BaseRepository[ResourceMember]):
    """Repository for ResourceMember data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(ResourceMember, session)

    async def get_by_resource(
            self,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
    ) -> List[ResourceMember]:
        """Get all members of a resource."""
        return await self.list(
            filters=[
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id,
            ]
        )

    async def get_by_user_and_resource(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
    ) -> Optional[ResourceMember]:
        """Get a specific user's membership in a resource."""
        return await self.get_one([
            ResourceMember.user_id == user_id,
            ResourceMember.resource_type == resource_type,
            ResourceMember.resource_id == resource_id,
        ])

    async def get_by_user(
            self,
            user_id: uuid.UUID,
            resource_type: Optional[ResourceType] = None,
    ) -> List[ResourceMember]:
        """Get all resource memberships for a user, optionally filtered by resource type."""
        filters: List[Any] = [ResourceMember.user_id == user_id]
        if resource_type:
            filters.append(ResourceMember.resource_type == resource_type)
        return await self.list(filters=filters)

    async def get_resource_ids_by_user(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
    ) -> List[uuid.UUID]:
        """Get all resource IDs where the user is a member."""
        members = await self.get_by_user(user_id, resource_type)
        return [member.resource_id for member in members]

    async def get_resource_ids_by_user_with_permission(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            required_permission: Permission | str,
    ) -> List[uuid.UUID]:
        """Get resource IDs where user's resource role satisfies required permission."""
        required_perm = (
            required_permission
            if isinstance(required_permission, Permission)
            else parse_permission(required_permission)
        )

        rows = await self.session.exec(
            select(ResourceMember.resource_id, RolePermission.permission)
            .join(RolePermission, RolePermission.role_id == ResourceMember.role_id)
            .where(
                ResourceMember.user_id == user_id,
                ResourceMember.resource_type == resource_type,
            )
        )

        permissions_by_resource: dict[uuid.UUID, set[str]] = {}
        for resource_id, permission in rows.all():
            permissions_by_resource.setdefault(resource_id, set()).add(permission)

        return [
            resource_id
            for resource_id, permissions in permissions_by_resource.items()
            if required_perm.is_satisfied_by(permissions)
        ]

    async def get_by_user_and_resource_with_expired(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
    ) -> Optional[ResourceMember]:
        """Get a specific user's membership in a resource (including expired)."""
        return await self.get_by_user_and_resource(user_id, resource_type, resource_id)

    async def get_user_role_in_resource(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
    ) -> Optional["Role"]:
        """
        Efficiently get user's role in a resource using SQL JOIN.
        
        Returns the Role object directly without fetching ResourceMember first.
        
        Args:
            user_id: User ID
            resource_type: Resource type
            resource_id: Resource ID
            
        Returns:
            Role object if user is a member, None otherwise
        """
        # Single SQL query with JOIN to get role directly
        statement = (
            select(Role)
            .join(ResourceMember)
            .where(
                ResourceMember.user_id == user_id,
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id
            )
        )
        result = await self.session.exec(statement)
        return result.first()

    @transactional
    async def assign_role(
            self,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
            user_id: uuid.UUID,
            role_id: uuid.UUID,
    ) -> ResourceMember:
        """
        Assign a role to a user for a resource.
        
        This is used when creating new resource member assignments or changing roles.
        
        Args:
            resource_type: Type of resource (e.g., ResourceType.DATASET)
            resource_id: The resource's ID
            user_id: The user ID to assign the role to
            role_id: The ID of the role to assign
            
        Returns:
            The created or updated ResourceMember entry
        """
        member = ResourceMember(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            role_id=role_id,
        )
        return await self.create(member.model_dump())
