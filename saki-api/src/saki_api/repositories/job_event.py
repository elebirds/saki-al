"""
JobEvent Repository - Data access layer for persisted runtime events.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.job_event import JobEvent
from saki_api.repositories.base import BaseRepository


class JobEventRepository(BaseRepository[JobEvent]):
    """Repository for JobEvent data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(JobEvent, session)

    async def list_by_job_after_seq(self, job_id: uuid.UUID, after_seq: int) -> List[JobEvent]:
        return await self.list(
            filters=[JobEvent.job_id == job_id, JobEvent.seq > after_seq],
            order_by=[JobEvent.seq.asc()],
        )
