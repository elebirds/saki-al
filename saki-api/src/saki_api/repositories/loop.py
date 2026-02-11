"""
Loop Repository - Data access layer for ALLoop operations.
"""

import uuid
from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import ALLoopStatus
from saki_api.models.l3.loop import ALLoop
from saki_api.repositories.base import BaseRepository


class LoopRepository(BaseRepository[ALLoop]):
    """Repository for ALLoop data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(ALLoop, session)

    async def get_active_by_branch(self, branch_id: uuid.UUID) -> Optional[ALLoop]:
        return await self.get_one(
            filters=[ALLoop.branch_id == branch_id, ALLoop.status == ALLoopStatus.RUNNING]
        )

    async def list_by_project(self, project_id: uuid.UUID) -> List[ALLoop]:
        return await self.list(
            filters=[ALLoop.project_id == project_id],
            order_by=[ALLoop.updated_at.desc()],
        )
