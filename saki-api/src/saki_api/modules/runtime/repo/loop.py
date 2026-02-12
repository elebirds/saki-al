"""
Loop Repository - Data access layer for ALLoop operations.
"""

import uuid
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.loop import ALLoop
from saki_api.modules.shared.modeling.enums import ALLoopStatus


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

    async def list_running_ids(self) -> List[uuid.UUID]:
        rows = await self.session.exec(
            select(ALLoop.id).where(ALLoop.status == ALLoopStatus.RUNNING)
        )
        return [item for item in rows.all()]

    async def list_by_experiment_group(self, experiment_group_id: uuid.UUID) -> List[ALLoop]:
        stmt = (
            select(ALLoop)
            .where(ALLoop.experiment_group_id == experiment_group_id)
            .order_by(ALLoop.created_at.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
