"""Repository for AL snapshot versions."""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion


class ALSnapshotVersionRepository(BaseRepository[ALSnapshotVersion]):
    def __init__(self, session: AsyncSession):
        super().__init__(ALSnapshotVersion, session)

    async def get_latest_by_loop(self, loop_id: uuid.UUID) -> ALSnapshotVersion | None:
        stmt = (
            select(ALSnapshotVersion)
            .where(ALSnapshotVersion.loop_id == loop_id)
            .order_by(ALSnapshotVersion.version_index.desc(), ALSnapshotVersion.created_at.desc())
            .limit(1)
        )
        return (await self.session.exec(stmt)).first()

    async def list_by_loop(self, loop_id: uuid.UUID) -> list[ALSnapshotVersion]:
        stmt = (
            select(ALSnapshotVersion)
            .where(ALSnapshotVersion.loop_id == loop_id)
            .order_by(ALSnapshotVersion.version_index.asc(), ALSnapshotVersion.created_at.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def next_version_index(self, loop_id: uuid.UUID) -> int:
        stmt = select(func.max(ALSnapshotVersion.version_index)).where(ALSnapshotVersion.loop_id == loop_id)
        max_version = (await self.session.exec(stmt)).one_or_none()
        return int(max_version or 0) + 1
