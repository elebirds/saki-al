"""Annotation module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.annotation.repo.annotation import AnnotationRepository
from saki_api.modules.annotation.repo.camap import CAMapRepository
from saki_api.modules.annotation.repo.draft import AnnotationDraftRepository
from saki_api.modules.project.repo.commit_sample_state import CommitSampleStateRepository
from saki_api.modules.shared.modeling.enums import CommitSampleReviewState


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
        self.commit_sample_state_repo = CommitSampleStateRepository(session)
        self.draft_repo = AnnotationDraftRepository(session)

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

    async def list_labeled_sample_ids_at_commit(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID] | None = None,
    ) -> list[uuid.UUID]:
        return await self.commit_sample_state_repo.list_labeled_sample_ids(
            commit_id=commit_id,
            sample_ids=sample_ids,
        )

    async def list_review_states_at_commit(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, CommitSampleReviewState]:
        return await self.commit_sample_state_repo.list_review_states_by_sample_ids(
            commit_id=commit_id,
            sample_ids=sample_ids,
        )

    async def count_annotations_by_sample_at_commit(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        return await self.camap_repo.count_annotations_by_sample_ids(
            commit_id=commit_id,
            sample_ids=sample_ids,
        )

    async def list_draft_sample_ids(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        branch_name: str,
        sample_ids: list[uuid.UUID] | None = None,
    ) -> list[uuid.UUID]:
        return await self.draft_repo.list_sample_ids_by_scope(
            project_id=project_id,
            user_id=user_id,
            branch_name=branch_name,
            sample_ids=sample_ids,
        )

    async def list_drafts_by_samples(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        branch_name: str,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, AnnotationDraft]:
        rows = await self.draft_repo.list_by_scope_and_samples(
            project_id=project_id,
            user_id=user_id,
            branch_name=branch_name,
            sample_ids=sample_ids,
        )
        return {row.sample_id: row for row in rows}
