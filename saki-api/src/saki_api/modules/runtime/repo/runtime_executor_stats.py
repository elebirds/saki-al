"""Repository for RuntimeExecutorStats snapshots."""

from datetime import datetime
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.runtime_executor_stats import RuntimeExecutorStats


class RuntimeExecutorStatsRepository(BaseRepository[RuntimeExecutorStats]):
    def __init__(self, session: AsyncSession):
        super().__init__(RuntimeExecutorStats, session)

    async def list_since(self, start_at: datetime) -> List[RuntimeExecutorStats]:
        stmt = (
            select(RuntimeExecutorStats)
            .where(RuntimeExecutorStats.ts >= start_at)
            .order_by(RuntimeExecutorStats.ts.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
