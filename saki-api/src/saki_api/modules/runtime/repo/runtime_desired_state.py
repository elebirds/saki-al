from __future__ import annotations

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.runtime_desired_state import RuntimeDesiredState


class RuntimeDesiredStateRepository(BaseRepository[RuntimeDesiredState]):
    def __init__(self, session: AsyncSession):
        super().__init__(RuntimeDesiredState, session)

    async def get_by_component(
        self,
        *,
        component_type: str,
        component_name: str,
    ) -> Optional[RuntimeDesiredState]:
        stmt = select(RuntimeDesiredState).where(
            RuntimeDesiredState.component_type == component_type,
            RuntimeDesiredState.component_name == component_name,
        )
        rows = await self.session.exec(stmt)
        return rows.first()
