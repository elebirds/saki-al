"""Prediction-task oriented helper queries."""

from __future__ import annotations

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft


class PredictionQueryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_drafts_by_scope_and_samples(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        branch_name: str,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, AnnotationDraft]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return {}
        stmt = select(AnnotationDraft).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == user_id,
            AnnotationDraft.branch_name == branch_name,
            AnnotationDraft.sample_id.in_(unique_sample_ids),
        )
        rows = await self.session.exec(stmt)
        return {row.sample_id: row for row in rows.all()}

    async def list_commit_annotations_by_samples(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> list[tuple[uuid.UUID, Annotation]]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return []
        stmt = (
            select(CommitAnnotationMap.sample_id, Annotation)
            .join(Annotation, Annotation.id == CommitAnnotationMap.annotation_id)
            .where(
                CommitAnnotationMap.commit_id == commit_id,
                CommitAnnotationMap.sample_id.in_(unique_sample_ids),
            )
        )
        rows = await self.session.exec(stmt)
        return list(rows.all())
