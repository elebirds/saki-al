from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
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

    async def find_latest_reusable_uploaded_session(
        self,
        *,
        user_id: uuid.UUID,
        file_sha256: str,
        size: int,
        now: datetime | None = None,
    ) -> ImportUploadSession | None:
        ts = now or datetime.now(UTC)
        stmt = (
            select(ImportUploadSession)
            .where(
                ImportUploadSession.user_id == user_id,
                ImportUploadSession.file_sha256 == file_sha256,
                ImportUploadSession.size == size,
                ImportUploadSession.status.in_(["uploaded", "consumed"]),
                or_(ImportUploadSession.expires_at.is_(None), ImportUploadSession.expires_at > ts),
            )
            .order_by(
                ImportUploadSession.completed_at.desc().nullslast(),
                ImportUploadSession.updated_at.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def has_live_object_reference(
        self,
        *,
        object_key: str,
        exclude_session_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> bool:
        ts = now or datetime.now(UTC)
        stmt = select(ImportUploadSession.id).where(
            ImportUploadSession.object_key == object_key,
            ImportUploadSession.status.in_(["initiated", "uploading", "uploaded", "consumed"]),
            or_(ImportUploadSession.expires_at.is_(None), ImportUploadSession.expires_at > ts),
        )
        if exclude_session_id is not None:
            stmt = stmt.where(ImportUploadSession.id != exclude_session_id)
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.first() is not None
