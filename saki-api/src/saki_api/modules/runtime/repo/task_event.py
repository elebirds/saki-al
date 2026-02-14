"""Repository for StepEvent persistence and queries."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step_event import StepEvent


class StepEventRepository(BaseRepository[StepEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(StepEvent, session)

    async def exists_by_step_seq(self, *, step_id: uuid.UUID, seq: int) -> bool:
        stmt = select(StepEvent.id).where(StepEvent.step_id == step_id, StepEvent.seq == seq).limit(1)
        row = (await self.session.exec(stmt)).first()
        return row is not None

    async def list_by_step_after_seq(
        self,
        *,
        step_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
    ) -> List[StepEvent]:
        stmt = (
            select(StepEvent)
            .where(StepEvent.step_id == step_id, StepEvent.seq > after_seq)
            .order_by(StepEvent.seq.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_step_and_types(self, *, step_id: uuid.UUID, event_types: List[str]) -> int:
        if not event_types:
            return 0
        stmt = delete(StepEvent).where(
            StepEvent.step_id == step_id,
            StepEvent.event_type.in_(event_types),
        )
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)

    # Backward aliases.
    async def exists_by_task_seq(self, *, task_id: uuid.UUID, seq: int) -> bool:
        return await self.exists_by_step_seq(step_id=task_id, seq=seq)

    async def list_by_task_after_seq(self, *, task_id: uuid.UUID, after_seq: int = 0, limit: int = 5000):
        return await self.list_by_step_after_seq(step_id=task_id, after_seq=after_seq, limit=limit)

    async def delete_by_task_and_types(self, *, task_id: uuid.UUID, event_types: List[str]) -> int:
        return await self.delete_by_step_and_types(step_id=task_id, event_types=event_types)


TaskEventRepository = StepEventRepository
