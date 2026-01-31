"""
Permission Service - Business logic for permission queries.
"""

import uuid
from typing import Set

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.repositories.permission import PermissionRepository


class PermissionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.permission_repo = PermissionRepository(session)
    
    async def get_role_permissions(self, role_id: uuid.UUID) -> Set[str]:
        role_perms = await self.permission_repo.list_by_role(role_id)
        return {rp.permission for rp in role_perms}