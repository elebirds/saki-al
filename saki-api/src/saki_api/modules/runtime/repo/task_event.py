"""Repository for TaskEvent persistence and queries."""

import uuid
from typing import List

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.task_event import TaskEvent


class TaskEventRepository(BaseRepository[TaskEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskEvent, session)

    async def exists_by_task_seq(self, *, task_id: uuid.UUID, seq: int) -> bool:
        stmt = select(TaskEvent.id).where(TaskEvent.task_id == task_id, TaskEvent.seq == seq).limit(1)
        row = (await self.session.exec(stmt)).first()
        return row is not None

    async def list_by_task_after_seq(
        self,
        *,
        task_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
    ) -> List[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.seq > after_seq)
            .order_by(TaskEvent.seq.asc())
            .limit(limit)
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def delete_by_task_and_types(self, *, task_id: uuid.UUID, event_types: List[str]) -> int:
        if not event_types:
            return 0
        stmt = delete(TaskEvent).where(
            TaskEvent.task_id == task_id,
            TaskEvent.event_type.in_(event_types),
        )
        result = await self.session.exec(stmt)
        return int(result.rowcount or 0)
