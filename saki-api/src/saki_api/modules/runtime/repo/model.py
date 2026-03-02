"""Repository for runtime model registry."""

import uuid
from typing import List

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.model import Model


class ModelRepository(BaseRepository[Model]):
    def __init__(self, session: AsyncSession):
        super().__init__(Model, session)

    async def list_by_project(
            self,
            project_id: uuid.UUID,
            *,
            limit: int = 100,
            offset: int = 0,
            status: str | None = None,
            plugin_id: str | None = None,
            source_round_id: uuid.UUID | None = None,
            q: str | None = None,
    ) -> List[Model]:
        stmt = select(Model).where(Model.project_id == project_id)

        if status:
            stmt = stmt.where(Model.status == status)
        if plugin_id:
            stmt = stmt.where(Model.plugin_id == plugin_id)
        if source_round_id is not None:
            stmt = stmt.where(Model.source_round_id == source_round_id)
        if q:
            q_like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Model.name.ilike(q_like),
                    Model.version_tag.ilike(q_like),
                    Model.plugin_id.ilike(q_like),
                )
            )

        stmt = (
            stmt.order_by(Model.created_at.desc())
            .offset(max(0, int(offset or 0)))
            .limit(max(1, int(limit or 100)))
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

    async def get_by_publish_key(
            self,
            *,
            project_id: uuid.UUID,
            source_round_id: uuid.UUID,
            primary_artifact_name: str,
            version_tag: str,
    ) -> Model | None:
        stmt = select(Model).where(
            Model.project_id == project_id,
            Model.source_round_id == source_round_id,
            Model.primary_artifact_name == primary_artifact_name,
            Model.version_tag == version_tag,
        )
        rows = await self.session.exec(stmt)
        return rows.first()
