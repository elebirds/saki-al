"""Snapshot-oriented read queries for runtime."""

from __future__ import annotations

import uuid

from sqlalchemy import asc, desc, distinct, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.runtime.domain.al_loop_visibility import ALLoopVisibility
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.shared.modeling.enums import CommitSampleReviewState, StepType
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


class SnapshotQueryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_samples_by_ids(self, *, sample_ids: list[uuid.UUID]) -> list[Sample]:
        unique_sample_ids = list(dict.fromkeys(sample_ids))
        if not unique_sample_ids:
            return []
        stmt = select(Sample).where(Sample.id.in_(unique_sample_ids)).order_by(Sample.id.asc())
        rows = await self.session.exec(stmt)
        return list(rows.all())

    async def list_selected_sample_ids_by_round(self, *, round_id: uuid.UUID) -> list[uuid.UUID]:
        min_rank = func.min(TaskCandidateItem.rank).label("min_rank")
        stmt = (
            select(TaskCandidateItem.sample_id, min_rank)
            .join(Step, Step.task_id == TaskCandidateItem.task_id)
            .where(
                Step.round_id == round_id,
                Step.step_type == StepType.SELECT,
                Step.task_id.is_not(None),
            )
            .group_by(TaskCandidateItem.sample_id)
            .order_by(min_rank.asc(), TaskCandidateItem.sample_id.asc())
        )
        rows = await self.session.exec(stmt)
        return [sample_id for sample_id, _ in rows.all()]

    async def list_visible_sample_ids(
        self,
        *,
        loop_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return set()
        stmt = select(ALLoopVisibility.sample_id).where(
            ALLoopVisibility.loop_id == loop_id,
            ALLoopVisibility.visible_in_train.is_(True),
            ALLoopVisibility.sample_id.in_(unique_sample_ids),
        )
        rows = await self.session.exec(stmt)
        return set(rows.all())

    async def list_labeled_sample_ids(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return set()
        stmt = select(distinct(CommitSampleState.sample_id)).where(
            CommitSampleState.commit_id == commit_id,
            CommitSampleState.sample_id.in_(unique_sample_ids),
            CommitSampleState.state.in_(
                (
                    CommitSampleReviewState.LABELED,
                    CommitSampleReviewState.EMPTY_CONFIRMED,
                )
            ),
        )
        rows = await self.session.exec(stmt)
        return set(rows.all())

    async def list_dataset_stats_for_samples(self, *, sample_ids: list[uuid.UUID]) -> list[dict]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return []
        stmt = (
            select(Sample.dataset_id, Dataset.name, func.count(Sample.id))
            .join(Dataset, Dataset.id == Sample.dataset_id)
            .where(Sample.id.in_(unique_sample_ids))
            .group_by(Sample.dataset_id, Dataset.name)
        )
        rows = await self.session.exec(stmt)
        return [
            {
                "dataset_id": dataset_id,
                "dataset_name": str(dataset_name or ""),
                "count": int(total or 0),
            }
            for dataset_id, dataset_name, total in rows.all()
        ]

    async def count_samples(
        self,
        *,
        sample_ids: list[uuid.UUID],
        dataset_id: uuid.UUID | None,
        q: str | None,
    ) -> int:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return 0
        stmt = select(func.count()).select_from(Sample).where(Sample.id.in_(unique_sample_ids))
        if dataset_id is not None:
            stmt = stmt.where(Sample.dataset_id == dataset_id)
        text = str(q or "").strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(or_(Sample.name.ilike(pattern), Sample.remark.ilike(pattern)))
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def list_samples_page(
        self,
        *,
        sample_ids: list[uuid.UUID],
        dataset_id: uuid.UUID | None,
        q: str | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
    ) -> list[Sample]:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return []
        stmt = select(Sample).where(Sample.id.in_(unique_sample_ids))
        if dataset_id is not None:
            stmt = stmt.where(Sample.dataset_id == dataset_id)
        text = str(q or "").strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(or_(Sample.name.ilike(pattern), Sample.remark.ilike(pattern)))

        sort_map = {
            "name": Sample.name,
            "createdAt": Sample.created_at,
            "updatedAt": Sample.updated_at,
            "created_at": Sample.created_at,
            "updated_at": Sample.updated_at,
        }
        sort_column = sort_map.get(str(sort_by or "createdAt"), Sample.created_at)
        order_clause = asc(sort_column) if str(sort_order or "desc").lower() == "asc" else desc(sort_column)
        stmt = stmt.order_by(order_clause, Sample.id.asc()).offset(max(0, int(offset or 0))).limit(max(1, int(limit or 1)))
        rows = await self.session.exec(stmt)
        return list(rows.all())
