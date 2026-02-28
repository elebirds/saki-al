"""Loop repository - Data access layer for Loop operations."""

import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.shared.modeling.enums import LoopLifecycle


class LoopRepository(BaseRepository[Loop]):
    """Repository for Loop data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Loop, session)

    async def get_active_by_branch(self, branch_id: uuid.UUID) -> Optional[Loop]:
        return await self.get_one(
            filters=[Loop.branch_id == branch_id, Loop.lifecycle == LoopLifecycle.RUNNING]
        )

    async def list_by_project(self, project_id: uuid.UUID) -> List[Loop]:
        return await self.list(
            filters=[Loop.project_id == project_id],
            order_by=[Loop.updated_at.desc()],
        )

    async def list_running_ids(self) -> List[uuid.UUID]:
        rows = await self.session.exec(
            select(Loop.id).where(Loop.lifecycle == LoopLifecycle.RUNNING)
        )
        return [item for item in rows.all()]

    async def list_by_experiment_group(self, experiment_group_id: uuid.UUID) -> List[Loop]:
        stmt = (
            select(Loop)
            .where(Loop.experiment_group_id == experiment_group_id)
            .order_by(Loop.created_at.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
