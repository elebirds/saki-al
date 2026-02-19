from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import delete, func, insert, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.importing.domain import ImportTask, ImportTaskEvent


class ImportTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_task(self, payload: dict[str, Any]) -> ImportTask:
        task = ImportTask(**payload)
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_task(self, task_id: uuid.UUID) -> ImportTask | None:
        return await self.session.get(ImportTask, task_id)

    async def list_events_after(
        self,
        *,
        task_id: uuid.UUID,
        after_seq: int,
        limit: int = 500,
    ) -> list[ImportTaskEvent]:
        stmt = (
            select(ImportTaskEvent)
            .where(ImportTaskEvent.task_id == task_id, ImportTaskEvent.seq > after_seq)
            .order_by(ImportTaskEvent.seq.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_last_seq(self, *, task_id: uuid.UUID) -> int:
        stmt = select(func.max(ImportTaskEvent.seq)).where(ImportTaskEvent.task_id == task_id)
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def append_events(self, rows: Iterable[dict[str, Any]]) -> None:
        payload = list(rows)
        if not payload:
            return
        await self.session.execute(insert(ImportTaskEvent), payload)
        await self.session.flush()

    async def delete_old_tasks(self, *, older_than_hours: int) -> int:
        stmt = (
            delete(ImportTask)
            .where(
                ImportTask.finished_at.is_not(None),
                ImportTask.finished_at < func.now() - func.make_interval(hours=older_than_hours),
            )
        )
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)
