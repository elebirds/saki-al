"""Round repository - Data access layer for L3 Round operations."""

import uuid
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.round import Round


class RoundRepository(BaseRepository[Round]):
    """Repository for Round data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Round, session)

    async def get_by_id_with_relations(self, round_id: uuid.UUID) -> Optional[Round]:
        return await self.get_one(filters=[Round.id == round_id])

    async def get_latest_by_loop(self, loop_id: uuid.UUID) -> Optional[Round]:
        rounds = await self.list(
            filters=[Round.loop_id == loop_id],
            order_by=[Round.round_index.desc(), Round.created_at.desc()],
        )
        return rounds[0] if rounds else None

    async def list_by_loop(self, loop_id: uuid.UUID) -> List[Round]:
        return await self.list(filters=[Round.loop_id == loop_id], order_by=[Round.round_index.asc()])

    async def list_by_loop_desc(self, loop_id: uuid.UUID, *, limit: int = 50) -> List[Round]:
        stmt = (
            select(Round)
            .where(Round.loop_id == loop_id)
            .order_by(Round.round_index.desc(), Round.created_at.desc())
            .limit(max(1, limit))
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())


# Backward alias.
JobRepository = RoundRepository
