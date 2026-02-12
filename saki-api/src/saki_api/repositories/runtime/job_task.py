"""Repository for JobTask data access."""

import uuid
from typing import List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.runtime.job_task import JobTask
from saki_api.repositories.base import BaseRepository


class JobTaskRepository(BaseRepository[JobTask]):
    def __init__(self, session: AsyncSession):
        super().__init__(JobTask, session)

    async def list_by_job(self, job_id: uuid.UUID) -> List[JobTask]:
        return await self.list(
            filters=[JobTask.job_id == job_id],
            order_by=[JobTask.task_index.asc(), JobTask.created_at.asc()],
        )

    async def get_by_id_with_relations(self, task_id: uuid.UUID) -> Optional[JobTask]:
        return await self.get_one(filters=[JobTask.id == task_id])
