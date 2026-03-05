"""Repository for task event persistence and queries."""

from datetime import datetime
import uuid
from typing import Any, List

import sqlalchemy as sa
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_event import TaskEvent


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

    async def list_by_task_query(
        self,
        *,
        task_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
        event_types: List[str] | None = None,
        q: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> List[TaskEvent]:
        stmt = select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.seq > after_seq)
        if event_types:
            stmt = stmt.where(TaskEvent.event_type.in_(event_types))
        if from_ts is not None:
            stmt = stmt.where(TaskEvent.ts >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(TaskEvent.ts <= to_ts)
        if q:
            pattern = f"%{str(q).strip()}%"
            stmt = stmt.where(sa.cast(TaskEvent.payload, sa.Text).ilike(pattern))
        stmt = stmt.order_by(TaskEvent.seq.asc()).limit(limit)
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_by_round_after_cursor(
        self,
        *,
        round_id: uuid.UUID,
        task_ids: List[uuid.UUID],
        after_task_seq: dict[uuid.UUID, int],
        limit: int = 5000,
    ) -> list[tuple[TaskEvent, Step]]:
        if not task_ids:
            return []
        conditions: list[Any] = []
        for task_id in task_ids:
            threshold = max(0, int(after_task_seq.get(task_id, 0) or 0))
            conditions.append(sa.and_(TaskEvent.task_id == task_id, TaskEvent.seq > threshold))
        if not conditions:
            return []

        stmt = (
            select(TaskEvent, Step)
            .join(Step, Step.task_id == TaskEvent.task_id)
            .where(
                Step.round_id == round_id,
                Step.task_id.is_not(None),
                TaskEvent.task_id.in_(task_ids),
                sa.or_(*conditions),
            )
            .order_by(
                TaskEvent.ts.asc(),
                Step.step_index.asc(),
                TaskEvent.seq.asc(),
                TaskEvent.task_id.asc(),
            )
            .limit(max(1, min(int(limit or 5000), 100000)))
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

    async def exists_by_step_seq(self, *, step_id: uuid.UUID, seq: int) -> bool:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return False
        return await self.exists_by_task_seq(task_id=step.task_id, seq=seq)

    async def list_by_step_after_seq(
        self,
        *,
        step_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
    ) -> List[TaskEvent]:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return []
        return await self.list_by_task_after_seq(task_id=step.task_id, after_seq=after_seq, limit=limit)

    async def list_by_step_query(
        self,
        *,
        step_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
        event_types: List[str] | None = None,
        q: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> List[TaskEvent]:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return []
        return await self.list_by_task_query(
            task_id=step.task_id,
            after_seq=after_seq,
            limit=limit,
            event_types=event_types,
            q=q,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    async def delete_by_step_and_types(self, *, step_id: uuid.UUID, event_types: List[str]) -> int:
        step = await self.session.get(Step, step_id)
        if step is None or step.task_id is None:
            return 0
        return await self.delete_by_task_and_types(task_id=step.task_id, event_types=event_types)


# Legacy alias, kept for incremental refactor of imports.
StepEventRepository = TaskEventRepository
