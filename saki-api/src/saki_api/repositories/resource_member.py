"""
Resource Member Repository - Data access layer for ResourceMember operations.
"""

import uuid
from typing import List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.models.rbac.enums import ResourceType
from saki_api.repositories.base import BaseRepository


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
        filters = [ResourceMember.user_id == user_id]
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
