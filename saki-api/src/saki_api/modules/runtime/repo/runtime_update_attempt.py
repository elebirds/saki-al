from __future__ import annotations

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.runtime_update_attempt import RuntimeUpdateAttempt


class RuntimeUpdateAttemptRepository(BaseRepository[RuntimeUpdateAttempt]):
    def __init__(self, session: AsyncSession):
        super().__init__(RuntimeUpdateAttempt, session)

    async def get_latest_by_executor(self, executor_id: str) -> Optional[RuntimeUpdateAttempt]:
        stmt = (
            select(RuntimeUpdateAttempt)
            .where(RuntimeUpdateAttempt.executor_id == executor_id)
            .order_by(RuntimeUpdateAttempt.started_at.desc(), RuntimeUpdateAttempt.created_at.desc())
            .limit(1)
        )
        rows = await self.session.exec(stmt)
        return rows.first()

    async def get_latest_failed_by_executor(self, executor_id: str) -> Optional[RuntimeUpdateAttempt]:
        stmt = (
            select(RuntimeUpdateAttempt)
            .where(
                RuntimeUpdateAttempt.executor_id == executor_id,
                RuntimeUpdateAttempt.status.in_(("failed", "rolled_back")),
            )
            .order_by(RuntimeUpdateAttempt.started_at.desc(), RuntimeUpdateAttempt.created_at.desc())
            .limit(1)
        )
        rows = await self.session.exec(stmt)
        return rows.first()
