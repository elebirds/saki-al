"""Repository for TaskEvent persistence and queries."""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.runtime.task_event import TaskEvent
from saki_api.repositories.base import BaseRepository


class TaskEventRepository(BaseRepository[TaskEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(TaskEvent, session)

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
