"""
Role Repository - Data access layer for Role operations.
"""

from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.shared.modeling import Role


class RoleRepository(BaseRepository[Role]):
    """Repository for Role data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Role, session)

    async def get_by_name(self, name: str) -> Role | None:
        """Get role by name."""
        return await self.get_one([Role.name == name])

    async def get_by_name_or_raise(self, name: str) -> Role:
        """Get role by name or raise NotFoundAppException."""
        return await self.get_one_or_raise([Role.name == name])

    async def list_system(self) -> List[Role]:
        """List all system preset roles."""
        return await self.list(
            filters=[Role.is_system == True],
            order_by=[Role.sort_order]
        )

    async def get_super_admin(self) -> Role:  # Must be NOT None
        return await self.get_one([Role.is_super_admin == True])

    async def get_default(self) -> Role:  # Must be NOT None
        """Get the default role for new users."""
        return await self.get_one([Role.is_default == True])
