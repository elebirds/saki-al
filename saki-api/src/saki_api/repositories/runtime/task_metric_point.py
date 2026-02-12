"""Repository for TaskMetricPoint time series."""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.task_metric_point import TaskMetricPoint
from saki_api.repositories.base import BaseRepository


class TaskMetricPointRepository(BaseRepository[TaskMetricPoint]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskMetricPoint, session)

    async def list_by_task(self, task_id: uuid.UUID, limit: int = 5000) -> List[TaskMetricPoint]:
        stmt = (
            select(TaskMetricPoint)
            .where(TaskMetricPoint.task_id == task_id)
            .order_by(TaskMetricPoint.step.asc(), TaskMetricPoint.created_at.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
