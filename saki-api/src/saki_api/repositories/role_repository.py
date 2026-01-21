"""
Role Repository - Data access layer for Role operations.
"""

import uuid
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models import Role, RolePermission, RoleType


class RoleRepository:
    """Repository for Role data access."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, role_id: uuid.UUID) -> Optional[Role]:
        """Get role by ID."""
        return await self.session.get(Role, role_id)

    async def get_by_name(self, name: str) -> Optional[Role]:
        """Get role by name."""
        statement = select(Role).where(Role.name == name)
        return (await self.session.exec(statement)).first()

    async def list_all(self, role_type: Optional[RoleType] = None) -> List[Role]:
        """List all roles, optionally filtered by type."""
        query = select(Role).order_by(Role.sort_order, Role.created_at)

        if role_type:
            query = query.where(Role.type == role_type)

        result = await self.session.exec(query)
        return result.all()

    async def list_system_roles(self) -> List[Role]:
        """List all system preset roles."""
        statement = select(Role).where(Role.is_system == True).order_by(Role.sort_order)
        result = await self.session.exec(statement)
        return result.all()

    async def get_default_role(self) -> Optional[Role]:
        """Get the default role for new users."""
        statement = select(Role).where(Role.is_default == True)
        return (await self.session.exec(statement)).first()

    async def create(self, role_data: dict) -> Role:
        """Create a new role."""
        role = Role(**role_data)
        self.session.add(role)
        await self.session.flush()
        return role

    async def update(self, role_id: uuid.UUID, role_data: dict) -> Optional[Role]:
        """Update an existing role."""
        role = await self.get_by_id(role_id)
        if not role:
            return None

        for key, value in role_data.items():
            setattr(role, key, value)

        self.session.add(role)
        await self.session.flush()
        return role

    async def delete(self, role_id: uuid.UUID) -> bool:
        """Delete a role."""
        role = await self.get_by_id(role_id)
        if not role:
            return False

        await self.session.delete(role)
        await self.session.flush()
        return True

    async def get_permissions(self, role_id: uuid.UUID) -> List[RolePermission]:
        """Get all permissions for a role."""
        statement = select(RolePermission).where(RolePermission.role_id == role_id)
        result = await self.session.exec(statement)
        return result.all()

    async def add_permission(self, role_id: uuid.UUID, permission: str,
                             conditions: Optional[dict] = None) -> RolePermission:
        """Add a permission to a role."""
        perm = RolePermission(
            role_id=role_id,
            permission=permission,
            conditions=conditions,
        )
        self.session.add(perm)
        await self.session.flush()
        return perm

    async def remove_permission(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> bool:
        """Remove a permission from a role."""
        perm = await self.session.get(RolePermission, permission_id)
        if not perm or perm.role_id != role_id:
            return False

        await self.session.delete(perm)
        await self.session.flush()
        return True

    async def clear_permissions(self, role_id: uuid.UUID) -> None:
        """Remove all permissions from a role."""
        perms = await self.get_permissions(role_id)
        for perm in perms:
            await self.session.delete(perm)
        await self.session.flush()

    async def commit(self) -> None:
        """Commit transaction."""
        await self.session.commit()

    async def refresh(self, obj: Role) -> None:
        """Refresh an object."""
        await self.session.refresh(obj)
