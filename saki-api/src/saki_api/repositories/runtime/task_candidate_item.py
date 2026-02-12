"""Repository for TaskCandidateItem queries."""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.runtime.task_candidate_item import TaskCandidateItem
from saki_api.repositories.base import BaseRepository


class TaskCandidateItemRepository(BaseRepository[TaskCandidateItem]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskCandidateItem, session)

    async def list_topk_by_task(self, task_id: uuid.UUID, limit: int = 200) -> List[TaskCandidateItem]:
        stmt = (
            select(TaskCandidateItem)
            .where(TaskCandidateItem.task_id == task_id)
            .order_by(TaskCandidateItem.score.desc(), TaskCandidateItem.rank.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
