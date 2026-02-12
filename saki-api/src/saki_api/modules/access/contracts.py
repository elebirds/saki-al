"""Access module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.access.api.user_system_role import UserSystemRoleCreate
from saki_api.modules.access.domain.rbac import ResourceMember, Role
from saki_api.modules.access.domain.rbac.enums import ResourceType
from saki_api.modules.access.repo.resource_member import ResourceMemberRepository
from saki_api.modules.access.repo.role import RoleRepository
from saki_api.modules.access.repo.user_system_role import UserSystemRoleRepository


@dataclass(slots=True)
class ResourceAccessDecisionDTO:
    resource_type: ResourceType
    resource_id: uuid.UUID
    allowed: bool


class AccessGuardContract(Protocol):
    async def can_read(self, *, user_id: uuid.UUID, resource_type: ResourceType, resource_id: uuid.UUID) -> bool:
        """Check resource read permission across modules."""


class AccessMembershipGateway:
    """Cross-module facade for resource membership and role lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.resource_member_repo = ResourceMemberRepository(session)
        self.role_repo = RoleRepository(session)
        self.user_role_repo = UserSystemRoleRepository(session)

    async def get_role(self, role_id: uuid.UUID) -> Role | None:
        return await self.role_repo.get_by_id(role_id)

    async def is_supremo_role(self, role_id: uuid.UUID) -> bool:
        role = await self.role_repo.get_by_id(role_id)
        return bool(role and role.is_supremo)

    async def assign_resource_role(
        self,
        *,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> ResourceMember:
        return await self.resource_member_repo.assign_role(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            role_id=role_id,
        )

    async def list_resource_members(
        self,
        *,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
        joinedloads: list | None = None,
    ) -> list[ResourceMember]:
        rows = await self.resource_member_repo.list(
            filters=[
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id,
            ],
            joinedloads=joinedloads,
        )
        return list(rows)

    async def get_member_by_user_and_resource(
        self,
        *,
        user_id: uuid.UUID,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
    ) -> ResourceMember | None:
        return await self.resource_member_repo.get_by_user_and_resource(user_id, resource_type, resource_id)

    async def create_member(self, payload: dict) -> ResourceMember:
        return await self.resource_member_repo.create(payload)

    async def update_member(self, member_id: uuid.UUID, payload: dict) -> ResourceMember | None:
        return await self.resource_member_repo.update(member_id, payload)

    async def delete_member(self, member_id: uuid.UUID) -> None:
        await self.resource_member_repo.delete(member_id)

    async def assign_system_role(self, *, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        await self.user_role_repo.assign(UserSystemRoleCreate(user_id=user_id, role_id=role_id))
