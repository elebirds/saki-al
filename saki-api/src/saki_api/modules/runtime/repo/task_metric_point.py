"""Repository for StepMetricPoint time series."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint


class StepMetricPointRepository(BaseRepository[StepMetricPoint]):
    def __init__(self, session: AsyncSession):
        super().__init__(StepMetricPoint, session)

    async def add_many(self, rows: List[StepMetricPoint]) -> None:
        for row in rows:
            self.session.add(row)

    async def list_by_step(self, step_id: uuid.UUID, limit: int = 5000) -> List[StepMetricPoint]:
        stmt = (
            select(StepMetricPoint)
            .where(StepMetricPoint.step_id == step_id)
            .order_by(StepMetricPoint.metric_step.asc(), StepMetricPoint.created_at.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_step(self, step_id: uuid.UUID) -> int:
        stmt = delete(StepMetricPoint).where(StepMetricPoint.step_id == step_id)
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)

    # Backward aliases.
    async def list_by_task(self, task_id: uuid.UUID, limit: int = 5000):
        return await self.list_by_step(task_id, limit)

    async def delete_by_task(self, task_id: uuid.UUID) -> int:
        return await self.delete_by_step(task_id)


TaskMetricPointRepository = StepMetricPointRepository
