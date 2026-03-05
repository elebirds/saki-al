"""Repository for unified runtime tasks."""

from __future__ import annotations

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.shared.modeling.enums import RuntimeTaskKind


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession):
        super().__init__(Task, session)

    async def list_by_project(self, project_id: uuid.UUID, *, limit: int = 100) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc())
            .limit(max(1, min(int(limit or 100), 1000)))
        )
        return list((await self.session.exec(stmt)).all())

    async def list_by_kind(self, *, kind: RuntimeTaskKind, limit: int = 100) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.kind == kind)
            .order_by(Task.created_at.desc())
            .limit(max(1, min(int(limit or 100), 1000)))
        )
        return list((await self.session.exec(stmt)).all())
