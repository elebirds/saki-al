"""
Sample Endpoints.
"""
import json
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Query, UploadFile
from loguru import logger
from sqlalchemy import asc, desc, or_
from starlette.responses import StreamingResponse

from saki_api.app.deps import AssetServiceDep, DatasetServiceDep, SampleServiceDep
from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.storage.api.sample import SampleRead
from saki_api.modules.storage.domain.sample import Sample

router = APIRouter()


@router.post(
    "/{dataset_id}/upload",
    response_model=List[SampleRead],
    dependencies=[
        Depends(
            require_permission(
                Permissions.SAMPLE_CREATE,
                ResourceType.DATASET,
                "dataset_id"
            )
        )
    ]
)
async def upload_samples(
        *,
        dataset_id: uuid.UUID,
        files: List[UploadFile] = File(...),
        dataset_service: DatasetServiceDep,
        sample_service: SampleServiceDep,
) -> List[SampleRead]:
    """
    Upload files to a dataset and return created samples.
    """
    dataset = await dataset_service.get_by_id_or_raise(dataset_id)
    return await sample_service.process_upload(dataset, files)


@router.post(
    "/{dataset_id}/stream",
    response_class=StreamingResponse,
    dependencies=[
        Depends(
            require_permission(
                Permissions.SAMPLE_CREATE,
                ResourceType.DATASET,
                "dataset_id"
            )
        )
    ]
)
async def upload_samples_with_progress(
        *,
        dataset_id: uuid.UUID,
        files: List[UploadFile] = File(...),
        dataset_service: DatasetServiceDep,
        sample_service: SampleServiceDep,
) -> StreamingResponse:
    """
    Upload samples with legacy SSE progress streaming.
    """
    dataset = await dataset_service.get_by_id_or_raise(dataset_id)

    async def generate_progress():
        async for event in sample_service.iter_upload_progress_events(dataset=dataset, files=files):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get(
    "/{dataset_id}/samples",
    response_model=PaginationResponse[SampleRead],
    dependencies=[
        Depends(
            require_permission(
                Permissions.SAMPLE_READ,
                ResourceType.DATASET,
                "dataset_id"
            )
        )
    ]
)
async def list_samples(
        *,
        dataset_id: uuid.UUID,
        sample_service: SampleServiceDep,
        asset_service: AssetServiceDep,
        q: str | None = Query(None, description="Search by name or remark"),
        page: int = Query(1, ge=1),
        limit: int = Query(24, ge=1, le=200),
        sort_by: str = "createdAt",
        sort_order: str = "desc",
) -> PaginationResponse[SampleRead]:
    """
    List all samples in a dataset.
    
    For each sample, includes a presigned URL for the primary asset (if set).
    This allows the frontend to directly display the primary image without additional requests.
    """
    sort_map = {
        "name": Sample.name,
        "createdAt": Sample.created_at,
        "updatedAt": Sample.updated_at,
        "created_at": Sample.created_at,
        "updated_at": Sample.updated_at,
    }
    sort_column = sort_map.get(sort_by, Sample.created_at)
    order_clause = asc(sort_column) if sort_order == "asc" else desc(sort_column)
    extra_filters = None
    normalized_q = q.strip() if q else None
    if normalized_q:
        pattern = f"%{normalized_q}%"
        extra_filters = [
            or_(
                Sample.name.ilike(pattern),
                Sample.remark.ilike(pattern),
            )
        ]

    pagination = Pagination.from_page(page=page, limit=limit)
    samples = await sample_service.repository.get_by_dataset_paginated(
        dataset_id,
        pagination=pagination,
        order_by=[order_clause],
        extra_filters=extra_filters,
    )

    result: List[SampleRead] = []
    for sample in samples.items:
        sample_dict = sample.model_dump() if hasattr(sample, 'model_dump') else sample.__dict__
        sample_read = SampleRead.model_validate(sample_dict)

        # Add presigned URL for primary asset if set
        if sample.primary_asset_id:
            try:
                primary_asset_url = await asset_service.get_presigned_download_url(sample.primary_asset_id)
                sample_read.primary_asset_url = primary_asset_url
            except Exception as e:
                logger.warning(
                    "获取资产预签名下载地址失败 asset_id={} error={}",
                    sample.primary_asset_id,
                    e,
                )

        result.append(sample_read)

    return PaginationResponse.from_items(
        items=result,
        total=samples.total,
        offset=samples.offset,
        limit=samples.limit,
    )


@router.delete(
    "/{dataset_id}/samples/{sample_id}",
    dependencies=[
        Depends(
            require_permission(
                Permissions.SAMPLE_DELETE,
                ResourceType.DATASET,
                "dataset_id"
            )
        )
    ]
)
async def delete_sample(
        *,
        dataset_id: uuid.UUID,
        sample_id: uuid.UUID,
        force: bool = Query(False, description="Force delete even if committed references exist"),
        sample_service: SampleServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """
    Delete a sample from a dataset.
    """
    return await sample_service.delete_sample_with_policy(
        dataset_id=dataset_id,
        sample_id=sample_id,
        actor_user_id=current_user_id,
        force=force,
    )
