"""Repository for model class schema rows."""

from __future__ import annotations

import uuid

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.model_class_schema import ModelClassSchema


class ModelClassSchemaRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_model(self, model_id: uuid.UUID) -> list[ModelClassSchema]:
        stmt = (
            select(ModelClassSchema)
            .where(ModelClassSchema.model_id == model_id)
            .order_by(ModelClassSchema.class_index.asc(), ModelClassSchema.id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def replace_for_model(self, *, model_id: uuid.UUID, rows: list[dict]) -> None:
        await self.session.exec(
            delete(ModelClassSchema).where(ModelClassSchema.model_id == model_id)
        )
        if rows:
            self.session.add_all([ModelClassSchema(model_id=model_id, **row) for row in rows])
        await self.session.flush()

    async def exists_by_label(self, label_id: uuid.UUID) -> bool:
        stmt = (
            select(ModelClassSchema.id)
            .where(ModelClassSchema.label_id == label_id)
            .limit(1)
        )
        return (await self.session.exec(stmt)).first() is not None
