"""Repository for StepEvent persistence and queries."""

from datetime import datetime
import uuid
from typing import List

import sqlalchemy as sa
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

    async def list_by_step_query(
        self,
        *,
        step_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
        event_types: List[str] | None = None,
        q: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> List[StepEvent]:
        stmt = select(StepEvent).where(StepEvent.step_id == step_id, StepEvent.seq > after_seq)
        if event_types:
            stmt = stmt.where(StepEvent.event_type.in_(event_types))
        if from_ts is not None:
            stmt = stmt.where(StepEvent.ts >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(StepEvent.ts <= to_ts)
        if q:
            pattern = f"%{str(q).strip()}%"
            stmt = stmt.where(sa.cast(StepEvent.payload, sa.Text).ilike(pattern))
        stmt = stmt.order_by(StepEvent.seq.asc()).limit(limit)
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
