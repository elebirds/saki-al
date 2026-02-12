"""
Job Repository - Data access layer for L3 Job operations.
"""

import uuid
from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.runtime.job import Job
from saki_api.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Repository for Job data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Job, session)

    async def get_by_id_with_relations(self, job_id: uuid.UUID) -> Optional[Job]:
        return await self.get_one(filters=[Job.id == job_id])

    async def get_latest_by_loop(self, loop_id: uuid.UUID) -> Optional[Job]:
        jobs = await self.list(
            filters=[Job.loop_id == loop_id],
            order_by=[Job.round_index.desc(), Job.created_at.desc()],
        )
        return jobs[0] if jobs else None

    async def list_by_loop(self, loop_id: uuid.UUID) -> List[Job]:
        return await self.list(filters=[Job.loop_id == loop_id], order_by=[Job.round_index.asc()])
