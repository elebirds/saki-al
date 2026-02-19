"""Annotation module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.repo.annotation import AnnotationRepository
from saki_api.modules.annotation.repo.camap import CAMapRepository


@dataclass(slots=True)
class DraftPresenceDTO:
    sample_id: uuid.UUID
    has_draft: bool


class AnnotationDraftReadContract(Protocol):
    async def has_user_draft(self, *, project_id: uuid.UUID, sample_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Check draft existence for projection/filter views."""


class AnnotationReadGateway:
    """Cross-module read facade for annotation/commit mapping data."""

    def __init__(self, session: AsyncSession) -> None:
        self.annotation_repo = AnnotationRepository(session)
        self.camap_repo = CAMapRepository(session)

    async def count_samples_at_commit(self, commit_id: uuid.UUID) -> int:
        return int(await self.camap_repo.count_samples_at_commit(commit_id))

    async def get_annotations_by_commit_and_sample(
        self,
        *,
        commit_id: uuid.UUID,
        sample_id: uuid.UUID,
    ) -> list[Annotation]:
        rows = await self.annotation_repo.get_by_commit_and_sample(commit_id, sample_id)
        return list(rows)

    async def get_annotations_by_commit_and_samples(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Annotation]]:
        return await self.annotation_repo.get_by_commit_and_samples(commit_id, sample_ids)
