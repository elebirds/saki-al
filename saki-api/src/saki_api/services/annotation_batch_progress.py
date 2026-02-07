from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import AnnotationBatchStatus
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem


def _apply_batch_status(
    *,
    batch: AnnotationBatch,
    items: list[AnnotationBatchItem],
    now: datetime,
) -> None:
    batch.total_count = len(items)
    batch.annotated_count = sum(1 for item in items if item.is_annotated)
    if batch.total_count == 0 or batch.annotated_count >= batch.total_count:
        batch.status = AnnotationBatchStatus.CLOSED
        if not batch.closed_at:
            batch.closed_at = now


async def refresh_batch_progress_by_commit(
    *,
    session: AsyncSession,
    batch: AnnotationBatch,
    commit_id: uuid.UUID,
) -> None:
    rows = await session.exec(
        select(AnnotationBatchItem).where(AnnotationBatchItem.batch_id == batch.id)
    )
    items = list(rows.all())
    if not items:
        _apply_batch_status(batch=batch, items=[], now=datetime.now(UTC))
        session.add(batch)
        return

    sample_ids = [item.sample_id for item in items]
    camap_rows = await session.exec(
        select(CommitAnnotationMap.sample_id)
        .where(
            CommitAnnotationMap.commit_id == commit_id,
            CommitAnnotationMap.sample_id.in_(sample_ids),
        )
        .distinct()
    )
    annotated_sample_ids = {row for row in camap_rows.all()}
    now = datetime.now(UTC)
    for item in items:
        if item.sample_id not in annotated_sample_ids:
            continue
        if not item.is_annotated:
            item.is_annotated = True
            item.annotated_at = now
        if item.annotation_commit_id != commit_id:
            item.annotation_commit_id = commit_id
        session.add(item)

    _apply_batch_status(batch=batch, items=items, now=now)
    session.add(batch)


async def backfill_open_batch_items_by_samples(
    *,
    session: AsyncSession,
    loop_id: uuid.UUID,
    sample_ids: list[uuid.UUID],
    commit_id: uuid.UUID,
) -> set[uuid.UUID]:
    if not sample_ids:
        return set()

    rows = await session.exec(
        select(AnnotationBatchItem, AnnotationBatch)
        .join(AnnotationBatch, AnnotationBatchItem.batch_id == AnnotationBatch.id)
        .where(
            AnnotationBatch.loop_id == loop_id,
            AnnotationBatch.status == AnnotationBatchStatus.OPEN,
            AnnotationBatchItem.sample_id.in_(sample_ids),
        )
    )
    pairs = list(rows.all())
    if not pairs:
        return set()

    touched_batch_ids: set[uuid.UUID] = set()
    now = datetime.now(UTC)
    for item, batch in pairs:
        touched_batch_ids.add(batch.id)
        if not item.is_annotated:
            item.is_annotated = True
            item.annotated_at = now
        if item.annotation_commit_id != commit_id:
            item.annotation_commit_id = commit_id
        session.add(item)

    for batch_id in touched_batch_ids:
        batch = await session.get(AnnotationBatch, batch_id)
        if not batch:
            continue
        item_rows = await session.exec(
            select(AnnotationBatchItem).where(AnnotationBatchItem.batch_id == batch_id)
        )
        items = list(item_rows.all())
        _apply_batch_status(batch=batch, items=items, now=now)
        session.add(batch)

    return touched_batch_ids
