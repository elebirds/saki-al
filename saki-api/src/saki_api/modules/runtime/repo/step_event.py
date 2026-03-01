"""Repository for StepEvent persistence and queries."""

from datetime import datetime
import uuid
from typing import Any, List

import sqlalchemy as sa
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step import Step
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

    async def list_by_round_after_cursor(
        self,
        *,
        round_id: uuid.UUID,
        step_ids: List[uuid.UUID],
        after_step_seq: dict[uuid.UUID, int],
        limit: int = 5000,
    ) -> list[tuple[StepEvent, Step]]:
        if not step_ids:
            return []
        conditions: list[Any] = []
        for step_id in step_ids:
            threshold = max(0, int(after_step_seq.get(step_id, 0) or 0))
            conditions.append(sa.and_(StepEvent.step_id == step_id, StepEvent.seq > threshold))
        if not conditions:
            return []

        stmt = (
            select(StepEvent, Step)
            .join(Step, Step.id == StepEvent.step_id)
            .where(
                Step.round_id == round_id,
                StepEvent.step_id.in_(step_ids),
                sa.or_(*conditions),
            )
            .order_by(
                StepEvent.ts.asc(),
                Step.step_index.asc(),
                StepEvent.seq.asc(),
                StepEvent.step_id.asc(),
            )
            .limit(max(1, min(int(limit or 5000), 100000)))
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
