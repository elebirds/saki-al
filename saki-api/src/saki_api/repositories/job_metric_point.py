"""
JobMetricPoint Repository - Data access layer for training metric series.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.repositories.base import BaseRepository


class JobMetricPointRepository(BaseRepository[JobMetricPoint]):
    """Repository for JobMetricPoint data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(JobMetricPoint, session)

    async def list_by_job(self, job_id: uuid.UUID, limit: int = 5000) -> List[JobMetricPoint]:
        points = await self.list(
            filters=[JobMetricPoint.job_id == job_id],
            order_by=[JobMetricPoint.step.asc(), JobMetricPoint.metric_name.asc()],
        )
        return points[:limit]
