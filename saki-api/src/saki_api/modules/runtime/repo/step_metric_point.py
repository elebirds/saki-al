"""Repository for StepMetricPoint time series."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint


class StepMetricPointRepository(BaseRepository[StepMetricPoint]):
    def __init__(self, session: AsyncSession):
        super().__init__(StepMetricPoint, session)

    async def add_many(self, rows: List[StepMetricPoint]) -> None:
        for row in rows:
            self.session.add(row)

    async def list_by_step(self, step_id: uuid.UUID, limit: int = 5000) -> List[StepMetricPoint]:
        stmt = (
            select(StepMetricPoint)
            .where(StepMetricPoint.step_id == step_id)
            .order_by(StepMetricPoint.metric_step.asc(), StepMetricPoint.created_at.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def latest_metrics_by_step_ids(self, step_ids: List[uuid.UUID]) -> dict[uuid.UUID, dict[str, float]]:
        if not step_ids:
            return {}
        stmt = (
            select(StepMetricPoint)
            .where(StepMetricPoint.step_id.in_(step_ids))
            .order_by(
                StepMetricPoint.step_id.asc(),
                StepMetricPoint.metric_name.asc(),
                StepMetricPoint.metric_step.desc(),
                StepMetricPoint.ts.desc(),
                StepMetricPoint.created_at.desc(),
            )
        )
        rows = await self.session.exec(stmt)
        latest: dict[uuid.UUID, dict[str, float]] = {}
        seen: set[tuple[uuid.UUID, str]] = set()
        for row in rows:
            if int(row.metric_step or 0) <= 0:
                continue
            key = (row.step_id, str(row.metric_name or ""))
            if not key[1]:
                continue
            if key in seen:
                continue
            seen.add(key)
            latest.setdefault(row.step_id, {})[key[1]] = float(row.metric_value)
        return latest

    async def delete_by_step(self, step_id: uuid.UUID) -> int:
        stmt = delete(StepMetricPoint).where(StepMetricPoint.step_id == step_id)
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)
