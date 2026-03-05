"""
AnnotationDraft Repository - Data access layer for AnnotationDraft operations.
"""

import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.annotation.domain.draft import AnnotationDraft


class AnnotationDraftRepository(BaseRepository[AnnotationDraft]):
    """Repository for AnnotationDraft data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(AnnotationDraft, session)

    async def get_by_unique(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Optional[AnnotationDraft]:
        statement = select(AnnotationDraft).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.sample_id == sample_id,
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.branch_name == branch_name,
        )
        result = await self.session.exec(statement)
        return result.first()

    async def list_by_user_project(
            self,
            user_id: uuid.UUID,
            project_id: uuid.UUID,
            branch_name: Optional[str] = None,
            sample_id: Optional[uuid.UUID] = None,
    ) -> List[AnnotationDraft]:
        filters = [
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.project_id == project_id,
        ]
        if branch_name:
            filters.append(AnnotationDraft.branch_name == branch_name)
        if sample_id:
            filters.append(AnnotationDraft.sample_id == sample_id)
        return await self.list(filters=filters, order_by=[AnnotationDraft.updated_at.desc()])

    async def delete_by_user_project(
            self,
            user_id: uuid.UUID,
            project_id: uuid.UUID,
            branch_name: Optional[str] = None,
            sample_id: Optional[uuid.UUID] = None,
    ) -> int:
        statement = select(AnnotationDraft).where(
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.project_id == project_id,
        )
        if branch_name:
            statement = statement.where(AnnotationDraft.branch_name == branch_name)
        if sample_id:
            statement = statement.where(AnnotationDraft.sample_id == sample_id)

        result = await self.session.exec(statement)
        drafts = result.all()
        count = len(drafts)
        for draft in drafts:
            await self.session.delete(draft)
        await self.session.flush()
        return count

    async def list_sample_ids_by_scope(
            self,
            *,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            sample_ids: List[uuid.UUID] | None = None,
    ) -> List[uuid.UUID]:
        statement = select(AnnotationDraft.sample_id).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.branch_name == branch_name,
        )
        if sample_ids is not None:
            unique_sample_ids = list(set(sample_ids))
            if not unique_sample_ids:
                return []
            statement = statement.where(AnnotationDraft.sample_id.in_(unique_sample_ids))
        rows = await self.session.exec(statement)
        return list(rows.all())

    async def list_by_scope_and_samples(
            self,
            *,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            sample_ids: List[uuid.UUID],
    ) -> List[AnnotationDraft]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return []
        statement = select(AnnotationDraft).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.branch_name == branch_name,
            AnnotationDraft.sample_id.in_(unique_sample_ids),
        )
        rows = await self.session.exec(statement)
        return list(rows.all())
