"""Repository for task metric point time series."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.task_metric_point import TaskMetricPoint


class TaskMetricPointRepository(BaseRepository[TaskMetricPoint]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskMetricPoint, session)

    async def add_many(self, rows: List[TaskMetricPoint]) -> None:
        for row in rows:
            self.session.add(row)

    async def list_by_task(self, task_id: uuid.UUID, limit: int = 5000) -> List[TaskMetricPoint]:
        stmt = (
            select(TaskMetricPoint)
            .where(TaskMetricPoint.task_id == task_id)
            .order_by(TaskMetricPoint.metric_step.asc(), TaskMetricPoint.created_at.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_task(self, task_id: uuid.UUID) -> int:
        stmt = delete(TaskMetricPoint).where(TaskMetricPoint.task_id == task_id)
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)
