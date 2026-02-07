"""
Annotation batch service for TopK -> annotation closed loop.
"""

from __future__ import annotations

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.models.enums import AnnotationBatchStatus
from saki_api.models.l2.branch import Branch
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.services.annotation_batch_progress import refresh_batch_progress_by_commit


class AnnotationBatchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_from_job(self, *, job_id: uuid.UUID, limit: int = 200) -> AnnotationBatch:
        job = await self.session.get(Job, job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")

        row = await self.session.exec(select(AnnotationBatch).where(AnnotationBatch.job_id == job_id))
        existing = row.first()
        if existing:
            return existing

        metric_rows = await self.session.exec(
            select(JobSampleMetric)
            .where(JobSampleMetric.job_id == job_id)
            .order_by(JobSampleMetric.score.desc())
            .limit(limit)
        )
        candidates = list(metric_rows.all())
        if not candidates:
            raise BadRequestAppException("No sampling candidates found for this job")

        batch = AnnotationBatch(
            project_id=job.project_id,
            loop_id=job.loop_id,
            job_id=job.id,
            round_index=max(1, int(job.round_index or job.iteration or 1)),
            status=AnnotationBatchStatus.OPEN,
            total_count=len(candidates),
            annotated_count=0,
            meta={"source": "job_sampling_topk"},
        )
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)

        for idx, item in enumerate(candidates, start=1):
            self.session.add(
                AnnotationBatchItem(
                    batch_id=batch.id,
                    sample_id=item.sample_id,
                    rank=idx,
                    score=float(item.score),
                    reason=dict(item.extra or {}),
                    prediction_snapshot=dict(item.prediction_snapshot or {}),
                    is_annotated=False,
                )
            )

        await self.session.commit()
        await self.session.refresh(batch)
        return batch

    async def get_batch_or_raise(self, batch_id: uuid.UUID) -> AnnotationBatch:
        batch = await self.session.get(AnnotationBatch, batch_id)
        if not batch:
            raise NotFoundAppException(f"AnnotationBatch {batch_id} not found")
        return batch

    async def list_items(self, batch_id: uuid.UUID, limit: int = 5000) -> list[AnnotationBatchItem]:
        await self.get_batch_or_raise(batch_id)
        rows = await self.session.exec(
            select(AnnotationBatchItem)
            .where(AnnotationBatchItem.batch_id == batch_id)
            .order_by(AnnotationBatchItem.rank.asc())
            .limit(limit)
        )
        return list(rows.all())

    async def refresh_progress(self, batch_id: uuid.UUID) -> AnnotationBatch:
        batch = await self.get_batch_or_raise(batch_id)
        job = await self.session.get(Job, batch.job_id)
        if not job:
            raise NotFoundAppException(f"Job {batch.job_id} not found for batch")

        # Use loop_id -> branch_id lookup through job.loop relationship.
        # Avoid joinedload here to keep service lightweight.
        from saki_api.models.l3.loop import ALLoop
        loop = await self.session.get(ALLoop, batch.loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {batch.loop_id} not found for batch")
        branch = await self.session.get(Branch, loop.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {loop.branch_id} not found for batch")

        await refresh_batch_progress_by_commit(
            session=self.session,
            batch=batch,
            commit_id=branch.head_commit_id,
        )
        await self.session.commit()
        await self.session.refresh(batch)
        return batch
