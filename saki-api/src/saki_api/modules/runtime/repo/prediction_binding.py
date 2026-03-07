"""Repository for prediction binding snapshots."""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.prediction_binding import PredictionBinding


class PredictionBindingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_prediction_id(self, prediction_id: uuid.UUID) -> PredictionBinding | None:
        stmt = (
            select(PredictionBinding)
            .where(PredictionBinding.prediction_id == prediction_id)
            .limit(1)
        )
        return (await self.session.exec(stmt)).first()

    async def upsert(
        self,
        *,
        prediction_id: uuid.UUID,
        model_id: uuid.UUID,
        schema_hash: str,
        by_index_json: list[str],
        by_name_json: dict[str, Any],
    ) -> PredictionBinding:
        existing = await self.get_by_prediction_id(prediction_id)
        if existing is None:
            row = PredictionBinding(
                prediction_id=prediction_id,
                model_id=model_id,
                schema_hash=schema_hash,
                by_index_json=list(by_index_json),
                by_name_json=dict(by_name_json),
            )
            self.session.add(row)
            await self.session.flush()
            await self.session.refresh(row)
            return row

        existing.model_id = model_id
        existing.schema_hash = str(schema_hash or "")
        existing.by_index_json = list(by_index_json)
        existing.by_name_json = dict(by_name_json)
        self.session.add(existing)
        await self.session.flush()
        await self.session.refresh(existing)
        return existing
