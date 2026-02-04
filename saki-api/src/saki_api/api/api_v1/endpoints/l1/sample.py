"""
Sample Endpoints.
"""
import json
import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy import asc, desc
from starlette.responses import StreamingResponse

from saki_api.api.service_deps import DatasetServiceDep, SampleServiceDep, AssetServiceDep
from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.rbac.dependencies import require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.models.l1.sample import Sample
from saki_api.modules.annotation.base import EventType, ProgressInfo
from saki_api.repositories.query import Pagination
from saki_api.schemas.sample import SampleRead

router = APIRouter()
logger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)


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
    Upload files to a dataset.
    
    Processes files according to dataset type:
    - CLASSIC: Image files -> one sample per file
    - FEDO: TXT files -> one sample per file with generated visualizations
    
    All files are stored as assets in object storage.
    Handler configurations are automatically loaded from environment/config files.
    """
    # Get dataset and process upload
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
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep,
        sample_service: SampleServiceDep,
        files: List[UploadFile] = File(...),
):
    """
    Upload samples with SSE progress streaming.
    
    Returns a stream of Server-Sent Events (SSE) for real-time progress updates.
    Handler configurations are automatically loaded from environment/config files.
    
    Event Types:
    - start: Initial event with total file count
    - file_start: Before processing each file
    - progress: Progress updates during file processing
    - file_complete: After each file is processed
    - complete: Final event with summary
    
    Example Event:
    ```
    data: {"event": "progress", "file_index": 0, "stage": "fedo_parse", "message": "Parsing data file", "percentage": 50}
    ```
    """

    # Get dataset
    dataset = await dataset_service.get_by_id_or_raise(dataset_id)

    async def generate_progress():
        """Generator for SSE progress events."""
        results = []

        # Send initial event
        yield f"data: {json.dumps({'event': 'start', 'total': len(files)})}\n\n"

        for index, file in enumerate(files):
            # Send file start event
            yield f"data: {json.dumps({'event': 'file_start', 'index': index, 'filename': file.filename})}\n\n"

            try:
                # Define progress callback for this file
                def progress_callback(event_type: EventType, progress: ProgressInfo):
                    """Called by handler to report progress."""
                    nonlocal results
                    # Don't yield here - we'll collect events and yield them in the async context
                    # Store progress event for async yielding
                    progress_events.append({
                        'event': 'progress',
                        'file_index': index,
                        'filename': file.filename,
                        'stage': progress.stage,
                        'message': progress.message,
                        'percentage': progress.percentage,
                        'current': progress.current,
                        'total': progress.total,
                    })

                # Track progress events
                progress_events = []

                # Process single file with progress callback
                sample = await sample_service.process_single_file_with_progress(
                    dataset=dataset,
                    file=file,
                    progress_callback=progress_callback
                )

                # Yield all collected progress events
                for event in progress_events:
                    yield f"data: {json.dumps(event)}\n\n"

                # Success
                results.append({
                    "id": str(sample.id),
                    "filename": file.filename,
                    "status": "success"
                })

                yield f"data: {json.dumps({'event': 'file_complete', 'index': index, 'filename': file.filename, 'success': True, 'sample_id': str(sample.id)})}\n\n"

            except Exception as e:
                logger.error(f"Error uploading file {file.filename}: {e}", exc_info=True)
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": str(e)
                })
                yield f"data: {json.dumps({'event': 'file_error', 'index': index, 'filename': file.filename, 'error': str(e)})}\n\n"

        # Send completion event
        success_count = sum(1 for r in results if r.get('status') == 'success')
        error_count = len(results) - success_count

        yield f"data: {json.dumps({'event': 'complete', 'uploaded': success_count, 'errors': error_count, 'results': results})}\n\n"

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
    response_model=List[SampleRead],
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
        offset: int = 0,
        limit: int = 100,
        sort_by: str = "createdAt",
        sort_order: str = "desc",
) -> List[SampleRead]:
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

    samples = await sample_service.repository.get_by_dataset(
        dataset_id,
        pagination=Pagination(offset=offset, limit=limit),
        order_by=[order_clause],
    )

    result = []
    for sample in samples:
        sample_dict = sample.model_dump() if hasattr(sample, 'model_dump') else sample.__dict__
        sample_read = SampleRead.model_validate(sample_dict)

        # Add presigned URL for primary asset if set
        if sample.primary_asset_id:
            try:
                primary_asset_url = await asset_service.get_presigned_download_url(sample.primary_asset_id)
                sample_read.primary_asset_url = primary_asset_url
            except Exception as e:
                logger.warning(f"Failed to get presigned URL for asset {sample.primary_asset_id}: {str(e)}")

        result.append(sample_read)

    return result


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
        sample_service: SampleServiceDep,
) -> dict:
    """
    Delete a sample from a dataset.
    """
    sample = await sample_service.get_by_id_or_raise(sample_id)
    if sample.dataset_id != dataset_id:
        raise BadRequestAppException("Sample not found in dataset")

    await sample_service.repository.delete(sample_id)
    return {"ok": True, "message": "Sample deleted successfully"}
