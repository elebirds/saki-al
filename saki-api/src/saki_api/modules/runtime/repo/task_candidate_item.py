"""Repository for StepCandidateItem queries."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem


class StepCandidateItemRepository(BaseRepository[StepCandidateItem]):
    def __init__(self, session: AsyncSession):
        super().__init__(StepCandidateItem, session)

    async def list_by_step(self, step_id: uuid.UUID) -> List[StepCandidateItem]:
        stmt = (
            select(StepCandidateItem)
            .where(StepCandidateItem.step_id == step_id)
            .order_by(StepCandidateItem.rank.asc(), StepCandidateItem.created_at.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_step(self, step_id: uuid.UUID) -> int:
        stmt = delete(StepCandidateItem).where(StepCandidateItem.step_id == step_id)
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)

    async def list_topk_by_step(self, step_id: uuid.UUID, limit: int = 200) -> List[StepCandidateItem]:
        stmt = (
            select(StepCandidateItem)
            .where(StepCandidateItem.step_id == step_id)
            .order_by(StepCandidateItem.score.desc(), StepCandidateItem.rank.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    # Backward aliases.
    async def list_by_task(self, task_id: uuid.UUID):
        return await self.list_by_step(task_id)

    async def delete_by_task(self, task_id: uuid.UUID) -> int:
        return await self.delete_by_step(task_id)

    async def list_topk_by_task(self, task_id: uuid.UUID, limit: int = 200):
        return await self.list_topk_by_step(task_id, limit)


TaskCandidateItemRepository = StepCandidateItemRepository
