"""Repository for prediction items."""

from __future__ import annotations

import uuid

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.prediction_item import PredictionItem


class PredictionItemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_prediction_set(self, prediction_set_id: uuid.UUID, *, limit: int = 1000) -> list[PredictionItem]:
        stmt = (
            select(PredictionItem)
            .where(PredictionItem.prediction_set_id == prediction_set_id)
            .order_by(PredictionItem.rank.asc(), PredictionItem.sample_id.asc())
            .limit(max(1, min(int(limit or 1000), 10000)))
        )
        return list((await self.session.exec(stmt)).all())

    async def replace_rows(self, *, prediction_set_id: uuid.UUID, rows: list[dict]) -> None:
        await self.session.exec(
            delete(PredictionItem).where(PredictionItem.prediction_set_id == prediction_set_id)
        )
        if rows:
            self.session.add_all(
                [
                    PredictionItem(
                        prediction_set_id=prediction_set_id,
                        sample_id=row["sample_id"],
                        rank=int(row.get("rank") or 0),
                        score=float(row.get("score") or 0.0),
                        label_id=row.get("label_id"),
                        geometry=dict(row.get("geometry") or {}),
                        attrs=dict(row.get("attrs") or {}),
                        confidence=float(row.get("confidence") or 0.0),
                        meta=dict(row.get("meta") or {}),
                    )
                    for row in rows
                ]
            )
        await self.session.flush()
