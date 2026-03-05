"""Repository for StepCandidateItem queries."""

import uuid
from typing import List

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.shared.modeling.enums import StepType


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

    async def list_selected_sample_ids_by_round(self, round_id: uuid.UUID) -> List[uuid.UUID]:
        min_rank = func.min(StepCandidateItem.rank).label("min_rank")
        stmt = (
            select(StepCandidateItem.sample_id, min_rank)
            .join(Step, Step.id == StepCandidateItem.step_id)
            .where(
                Step.round_id == round_id,
                Step.step_type == StepType.SELECT,
            )
            .group_by(StepCandidateItem.sample_id)
            .order_by(min_rank.asc(), StepCandidateItem.sample_id.asc())
        )
        rows = await self.session.exec(stmt)
        return [sample_id for sample_id, _rank in rows.all()]
