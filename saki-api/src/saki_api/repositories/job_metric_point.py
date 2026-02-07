"""
JobMetricPoint Repository - Data access layer for training metric series.
"""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.repositories.base import BaseRepository


class JobMetricPointRepository(BaseRepository[JobMetricPoint]):
    """Repository for JobMetricPoint data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(JobMetricPoint, session)

    async def list_by_job(self, job_id: uuid.UUID, limit: int = 5000) -> List[JobMetricPoint]:
        safe_limit = max(1, min(int(limit), 100000))
        statement = (
            select(JobMetricPoint)
            .where(JobMetricPoint.job_id == job_id)
            .order_by(JobMetricPoint.step.asc(), JobMetricPoint.metric_name.asc())
            .limit(safe_limit)
        )
        result = await self.session.exec(statement)
        return list(result.all())
