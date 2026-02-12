"""Repository for JobTask data access."""

import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.shared.modeling.enums import JobTaskStatus


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

    async def list_pending_by_job(self, job_id: uuid.UUID) -> List[JobTask]:
        stmt = (
            select(JobTask)
            .where(JobTask.job_id == job_id, JobTask.status == JobTaskStatus.PENDING)
            .order_by(JobTask.task_index.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_active_by_job(self, job_id: uuid.UUID) -> List[JobTask]:
        stmt = select(JobTask).where(
            JobTask.job_id == job_id,
            JobTask.status.in_(
                [
                    JobTaskStatus.PENDING,
                    JobTaskStatus.DISPATCHING,
                    JobTaskStatus.RUNNING,
                    JobTaskStatus.RETRYING,
                ]
            ),
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_by_job_ids(self, job_ids: List[uuid.UUID]) -> List[JobTask]:
        if not job_ids:
            return []
        stmt = select(JobTask).where(JobTask.job_id.in_(job_ids))
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def get_by_ids(self, task_ids: List[uuid.UUID]) -> List[JobTask]:
        if not task_ids:
            return []
        stmt = select(JobTask).where(JobTask.id.in_(task_ids))
        rows = await self.session.exec(stmt)
        return list(rows.all())
