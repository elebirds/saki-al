"""Repository for Step data access."""

import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.shared.modeling.enums import StepStatus


class StepRepository(BaseRepository[Step]):
    def __init__(self, session: AsyncSession):
        super().__init__(Step, session)

    async def list_by_round(self, round_id: uuid.UUID) -> List[Step]:
        return await self.list(
            filters=[Step.round_id == round_id],
            order_by=[Step.step_index.asc(), Step.created_at.asc()],
        )

    async def get_by_id_with_relations(self, step_id: uuid.UUID) -> Optional[Step]:
        return await self.get_one(filters=[Step.id == step_id])

    async def list_pending_by_round(self, round_id: uuid.UUID) -> List[Step]:
        stmt = (
            select(Step)
            .where(Step.round_id == round_id, Step.state == StepStatus.PENDING)
            .order_by(Step.step_index.asc())
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_active_by_round(self, round_id: uuid.UUID) -> List[Step]:
        stmt = select(Step).where(
            Step.round_id == round_id,
            Step.state.in_(
                [
                    StepStatus.PENDING,
                    StepStatus.DISPATCHING,
                    StepStatus.SYNCING_ENV,
                    StepStatus.PROBING_RUNTIME,
                    StepStatus.BINDING_DEVICE,
                    StepStatus.RUNNING,
                    StepStatus.RETRYING,
                ]
            ),
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_by_round_ids(self, round_ids: List[uuid.UUID]) -> List[Step]:
        if not round_ids:
            return []
        stmt = select(Step).where(Step.round_id.in_(round_ids))
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def get_by_ids(self, step_ids: List[uuid.UUID]) -> List[Step]:
        if not step_ids:
            return []
        stmt = select(Step).where(Step.id.in_(step_ids))
        rows = await self.session.exec(stmt)
        return list(rows.all())
