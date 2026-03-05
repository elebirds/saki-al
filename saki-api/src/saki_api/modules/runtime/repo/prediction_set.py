"""Repository for predictions."""

from __future__ import annotations

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.prediction_set import Prediction


class PredictionRepository(BaseRepository[Prediction]):
    def __init__(self, session: AsyncSession):
        super().__init__(Prediction, session)

    async def list_by_project(self, project_id: uuid.UUID, *, limit: int = 100) -> list[Prediction]:
        stmt = (
            select(Prediction)
            .where(Prediction.project_id == project_id)
            .order_by(Prediction.created_at.desc())
            .limit(max(1, min(int(limit or 100), 1000)))
        )
        return list((await self.session.exec(stmt)).all())


# Temporary alias for residual imports during hard cut.
PredictionSetRepository = PredictionRepository
