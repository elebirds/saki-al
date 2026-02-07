import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.internal.deps import verify_internal_token
from saki_api.core.exceptions import NotFoundAppException
from saki_api.db.session import get_session
from saki_api.models.l1.sample import Sample
from saki_api.models.l1.asset import Asset
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.project import ProjectDataset
from saki_api.services.asset import AssetService

router = APIRouter(dependencies=[Depends(verify_internal_token)])


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(cursor)
    except ValueError:
        return 0


@router.get("/projects/{project_id}/labels")
async def list_project_labels(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    stmt = select(Label).where(Label.project_id == project_id).order_by(Label.id)
    result = await session.exec(stmt)
    labels = [
        {"id": str(label.id), "name": label.name, "color": label.color}
        for label in result.all()
    ]
    return {"items": labels, "next_cursor": None}


@router.get("/commits/{commit_id}/samples")
async def list_commit_samples(
    commit_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=5000),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    commit = await session.get(Commit, commit_id)
    if not commit:
        raise NotFoundAppException(f"Commit {commit_id} not found")

    dataset_stmt = select(ProjectDataset.dataset_id).where(
        ProjectDataset.project_id == commit.project_id
    )
    dataset_result = await session.exec(dataset_stmt)
    dataset_ids = [row[0] for row in dataset_result.all()]

    offset = _parse_cursor(cursor)
    stmt = (
        select(Sample)
        .where(Sample.dataset_id.in_(dataset_ids))
        .order_by(Sample.id)
        .offset(offset)
        .limit(limit + 1)
    )
    result = await session.exec(stmt)
    samples = list(result.all())

    next_cursor = None
    if len(samples) > limit:
        samples = samples[:limit]
        next_cursor = str(offset + limit)

    asset_service = AssetService(session)
    items: List[Dict[str, Any]] = []
    for sample in samples:
        uri = None
        width = 0
        height = 0
        if sample.primary_asset_id:
            asset = await session.get(Asset, sample.primary_asset_id)
            if asset:
                meta = asset.meta_info or {}
                width = int(meta.get("width") or 0)
                height = int(meta.get("height") or 0)
                try:
                    uri = await asset_service.get_presigned_download_url(asset.id)
                except Exception:
                    uri = None
        if not uri:
            continue
        items.append(
            {
                "id": str(sample.id),
                "uri": uri,
                "width": width,
                "height": height,
                "meta": sample.meta_info or {},
            }
        )

    return {"items": items, "next_cursor": next_cursor}


@router.get("/commits/{commit_id}/annotations")
async def list_commit_annotations(
    commit_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=5000),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    offset = _parse_cursor(cursor)
    stmt = (
        select(CommitAnnotationMap)
        .where(CommitAnnotationMap.commit_id == commit_id)
        .order_by(CommitAnnotationMap.sample_id)
        .offset(offset)
        .limit(limit + 1)
    )
    result = await session.exec(stmt)
    mappings = list(result.all())

    next_cursor = None
    if len(mappings) > limit:
        mappings = mappings[:limit]
        next_cursor = str(offset + limit)

    annotation_ids = [m.annotation_id for m in mappings]
    items: List[Dict[str, Any]] = []
    if annotation_ids:
        ann_stmt = select(Annotation).where(Annotation.id.in_(annotation_ids))
        ann_result = await session.exec(ann_stmt)
        anns = {ann.id: ann for ann in ann_result.all()}
        for mapping in mappings:
            ann = anns.get(mapping.annotation_id)
            if not ann:
                continue
            bbox_xywh = None
            obb = None
            if ann.type.value == "rect":
                data = ann.data or {}
                bbox_xywh = [
                    float(data.get("x", 0.0)),
                    float(data.get("y", 0.0)),
                    float(data.get("width", 0.0)),
                    float(data.get("height", 0.0)),
                ]
            elif ann.type.value == "obb":
                data = ann.data or {}
                cx = float(data.get("cx", 0.0))
                cy = float(data.get("cy", 0.0))
                w = float(data.get("width", 0.0))
                h = float(data.get("height", 0.0))
                bbox_xywh = [cx - w / 2, cy - h / 2, w, h]
                obb = data

            items.append(
                {
                    "id": str(ann.id),
                    "sample_id": str(ann.sample_id),
                    "category_id": str(ann.label_id),
                    "bbox_xywh": bbox_xywh or [0, 0, 0, 0],
                    "obb": obb,
                    "source": ann.source.value,
                    "confidence": ann.confidence,
                }
            )

    return {"items": items, "next_cursor": next_cursor}


@router.get("/commits/{commit_id}/unlabeled-samples")
async def list_unlabeled_samples(
    commit_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=5000),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    commit = await session.get(Commit, commit_id)
    if not commit:
        raise NotFoundAppException(f"Commit {commit_id} not found")

    dataset_stmt = select(ProjectDataset.dataset_id).where(
        ProjectDataset.project_id == commit.project_id
    )
    dataset_result = await session.exec(dataset_stmt)
    dataset_ids = [row[0] for row in dataset_result.all()]

    # Annotated sample IDs at commit
    ann_stmt = select(CommitAnnotationMap.sample_id).where(
        CommitAnnotationMap.commit_id == commit_id
    )
    ann_result = await session.exec(ann_stmt)
    annotated_ids = {row[0] for row in ann_result.all()}

    all_stmt = (
        select(Sample)
        .where(Sample.dataset_id.in_(dataset_ids))
        .order_by(Sample.id)
    )
    all_result = await session.exec(all_stmt)
    all_samples = [s for s in all_result.all() if s.id not in annotated_ids]

    offset = _parse_cursor(cursor)
    page = all_samples[offset: offset + limit]
    next_cursor = None
    if offset + limit < len(all_samples):
        next_cursor = str(offset + limit)

    asset_service = AssetService(session)
    items: List[Dict[str, Any]] = []
    for sample in page:
        uri = None
        width = 0
        height = 0
        if sample.primary_asset_id:
            asset = await session.get(Asset, sample.primary_asset_id)
            if asset:
                meta = asset.meta_info or {}
                width = int(meta.get("width") or 0)
                height = int(meta.get("height") or 0)
                try:
                    uri = await asset_service.get_presigned_download_url(asset.id)
                except Exception:
                    uri = None
        if not uri:
            continue
        items.append(
            {
                "id": str(sample.id),
                "uri": uri,
                "width": width,
                "height": height,
                "meta": sample.meta_info or {},
            }
        )

    return {"items": items, "next_cursor": next_cursor}
