"""
RuntimeExecutor Repository - Data access for runtime executor heartbeat/online state.
"""

from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.runtime.runtime_executor import RuntimeExecutor
from saki_api.repositories.base import BaseRepository


class RuntimeExecutorRepository(BaseRepository[RuntimeExecutor]):
    """Repository for RuntimeExecutor data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(RuntimeExecutor, session)

    async def get_by_executor_id(self, executor_id: str) -> Optional[RuntimeExecutor]:
        return await self.get_one(filters=[RuntimeExecutor.executor_id == executor_id])

    async def list_online(self) -> List[RuntimeExecutor]:
        return await self.list(
            filters=[RuntimeExecutor.is_online.is_(True)],
            order_by=[RuntimeExecutor.last_seen_at.desc()],
        )
