"""Repository for runtime model registry."""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.model import Model


class ModelRepository(BaseRepository[Model]):
    def __init__(self, session: AsyncSession):
        super().__init__(Model, session)

    async def list_by_project(self, project_id: uuid.UUID, *, limit: int = 100) -> List[Model]:
        stmt = (
            select(Model)
            .where(Model.project_id == project_id)
            .order_by(Model.created_at.desc())
            .limit(max(1, limit))
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_other_production_models(self, *, project_id: uuid.UUID, exclude_model_id: uuid.UUID) -> List[Model]:
        stmt = select(Model).where(
            Model.project_id == project_id,
            Model.status == "production",
            Model.id != exclude_model_id,
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
