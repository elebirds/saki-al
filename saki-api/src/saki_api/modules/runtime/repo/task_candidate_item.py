"""Repository for task candidate item queries."""

import uuid
from typing import List

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.shared.modeling.enums import StepType


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

    async def list_selected_sample_ids_by_round(self, round_id: uuid.UUID) -> List[uuid.UUID]:
        min_rank = func.min(TaskCandidateItem.rank).label("min_rank")
        stmt = (
            select(TaskCandidateItem.sample_id, min_rank)
            .join(Step, Step.task_id == TaskCandidateItem.task_id)
            .where(
                Step.round_id == round_id,
                Step.step_type == StepType.SELECT,
                Step.task_id.is_not(None),
            )
            .group_by(TaskCandidateItem.sample_id)
            .order_by(min_rank.asc(), TaskCandidateItem.sample_id.asc())
        )
        rows = await self.session.exec(stmt)
        return [sample_id for sample_id, _rank in rows.all()]

    async def list_by_step(self, step_id: uuid.UUID) -> List[TaskCandidateItem]:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return []
        return await self.list_by_task(step.task_id)

    async def delete_by_step(self, step_id: uuid.UUID) -> int:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return 0
        return await self.delete_by_task(step.task_id)

    async def list_topk_by_step(self, step_id: uuid.UUID, limit: int = 200) -> List[TaskCandidateItem]:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return []
        return await self.list_topk_by_task(step.task_id, limit=limit)
