from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.importing.domain import ImportUploadSession


class ImportUploadSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, payload: dict) -> ImportUploadSession:
        row = ImportUploadSession(**payload)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, session_id: uuid.UUID) -> ImportUploadSession | None:
        return await self.session.get(ImportUploadSession, session_id)

    async def list_expired_active(self, *, now: datetime | None = None, limit: int = 500) -> list[ImportUploadSession]:
        ts = now or datetime.now(UTC)
        stmt = (
            select(ImportUploadSession)
            .where(
                ImportUploadSession.expires_at.is_not(None),
                ImportUploadSession.expires_at < ts,
                ImportUploadSession.status.in_(["initiated", "uploading", "uploaded"]),
            )
            .order_by(ImportUploadSession.expires_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
