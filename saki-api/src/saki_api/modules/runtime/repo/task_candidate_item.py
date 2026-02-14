"""Repository for TaskCandidateItem queries."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem


class TaskCandidateItemRepository(BaseRepository[TaskCandidateItem]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskCandidateItem, session)

    async def list_by_task(self, task_id: uuid.UUID) -> List[TaskCandidateItem]:
        stmt = (
            select(TaskCandidateItem)
            .where(TaskCandidateItem.task_id == task_id)
            .order_by(TaskCandidateItem.rank.asc(), TaskCandidateItem.created_at.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_task(self, task_id: uuid.UUID) -> int:
        stmt = delete(TaskCandidateItem).where(TaskCandidateItem.task_id == task_id)
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)

    async def list_topk_by_task(self, task_id: uuid.UUID, limit: int = 200) -> List[TaskCandidateItem]:
        stmt = (
            select(TaskCandidateItem)
            .where(TaskCandidateItem.task_id == task_id)
            .order_by(TaskCandidateItem.score.desc(), TaskCandidateItem.rank.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
