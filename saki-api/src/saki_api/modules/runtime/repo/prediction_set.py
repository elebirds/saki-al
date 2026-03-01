"""Repository for prediction sets."""

from __future__ import annotations

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.prediction_set import PredictionSet


class PredictionSetRepository(BaseRepository[PredictionSet]):
    def __init__(self, session: AsyncSession):
        super().__init__(PredictionSet, session)

    async def list_by_loop(self, loop_id: uuid.UUID, *, limit: int = 100) -> list[PredictionSet]:
        stmt = (
            select(PredictionSet)
            .where(PredictionSet.loop_id == loop_id)
            .order_by(PredictionSet.created_at.desc())
            .limit(max(1, min(int(limit or 100), 1000)))
        )
        return list((await self.session.exec(stmt)).all())
