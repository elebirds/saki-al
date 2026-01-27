"""
API endpoints for Sample-level operations including annotations.
Samples belong to Datasets, not directly to Projects.
"""

import json
import logging
import shutil
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import func, desc, asc
from sqlmodel import Session, select

# Import annotation module for handler registry
from saki_api.annotation import (
    get_handler,
    discover_handlers,
    UploadContext,
    ProgressTracker,
)
from saki_api.core.config import settings
from saki_api.core.rbac import require_permission
from saki_api.db.session import get_session
from saki_api.models import (
    Dataset,
    Permissions, ResourceType,
)
from saki_api.models.l1.sample import Sample, SampleStatus
from saki_api.models.user import User

logger = logging.getLogger(__name__)

# Initialize handlers on module load
discover_handlers()

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class SortOrder(str, Enum):
    """Sort order options."""
    ASC = "asc"
    DESC = "desc"


class SampleSortField(str, Enum):
    """Available fields for sorting samples."""
    NAME = "name"
    STATUS = "status"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    REMARK = "remark"


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{dataset_id}", response_model=Dict[str, Any])
def read_samples(
        dataset_id: str,
        status: Optional[SampleStatus] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: Optional[SampleSortField] = None,
        sort_order: SortOrder = SortOrder.ASC,
        session: Session = Depends(get_session),
        _current_user: User = Depends(require_permission(
            Permissions.SAMPLE_READ,
            ResourceType.DATASET,
            "dataset_id"
        ))
):
    """
    Get samples for a dataset.
    
    Args:
        dataset_id: ID of the dataset
        status: Filter by sample status (optional)
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return
        sort_by: Field to sort by (name, status, created_at, updated_at, remark)
        sort_order: Sort order (asc or desc)
    """
    # Verify dataset exists
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    query = select(Sample).where(Sample.dataset_id == dataset_id)
    if status:
        query = query.where(Sample.status == status)

    # Apply sorting
    if sort_by:
        sort_field = getattr(Sample, sort_by.value, None)
        if sort_field is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort field: {sort_by}. Valid fields are: name, status, created_at, updated_at, remark"
            )

        if sort_order == SortOrder.DESC:
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))
    else:
        # Default sorting by created_at descending (newest first)
        query = query.order_by(desc(Sample.created_at))

    # Calculate total count for pagination
    count_query = select(func.count()).select_from(Sample).where(Sample.dataset_id == dataset_id)
    if status:
        count_query = count_query.where(Sample.status == status)
    total = session.exec(count_query).one()

    samples = session.exec(query.offset(skip).limit(limit)).all()

    return {"items": samples, "total": total}


@router.post("/{dataset_id}/stream")
async def upload_samples_with_progress(
        dataset_id: str,
        files: List[UploadFile] = File(...),
        session: Session = Depends(get_session),
        _current_user: User = Depends(require_permission(
            Permissions.SAMPLE_CREATE,
            ResourceType.DATASET,
            "dataset_id"
        ))
):
    """
    Upload samples with SSE progress streaming.
    Returns a stream of progress events during upload.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        handler = get_handler(dataset.annotation_system)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"No handler available for annotation system: {dataset.annotation_system.value}"
        )

    upload_dir = Path(settings.UPLOAD_DIR) / dataset_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    context = UploadContext(
        dataset_id=dataset_id,
        upload_dir=upload_dir,
        config={},
    )

    async def generate_progress():
        """Generator for SSE progress events."""
        tracker = ProgressTracker(total_files=len(files))
        results = []

        # Send initial event
        yield f"data: {json.dumps({'event': 'start', 'total': len(files)})}\n\n"

        handler.pre_upload(context)

        for index, file in enumerate(files):
            # Send file start event
            yield f"data: {json.dumps({'event': 'file_start', 'index': index, 'filename': file.filename})}\n\n"

            try:
                file_path = upload_dir / file.filename
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                result = handler.process_upload(file_path, context)

                if result.success:
                    sample_fields = result.sample_fields
                    sample = Sample(
                        dataset_id=dataset_id,
                        name=file.filename,
                        status=SampleStatus.UNLABELED,
                        **sample_fields
                    )
                    if result.sample_id:
                        sample.id = result.sample_id
                    session.add(sample)

                    results.append({
                        "id": sample.id,
                        "filename": file.filename,
                        "status": "success"
                    })

                    yield f"data: {json.dumps({'event': 'file_complete', 'index': index, 'filename': file.filename, 'success': True, 'sample_id': sample.id})}\n\n"
                else:
                    results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": result.error
                    })
                    yield f"data: {json.dumps({'event': 'file_complete', 'index': index, 'filename': file.filename, 'success': False, 'error': result.error})}\n\n"

            except Exception as e:
                logger.error(f"Error uploading file {file.filename}: {e}")
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": str(e)
                })
                yield f"data: {json.dumps({'event': 'file_error', 'index': index, 'filename': file.filename, 'error': str(e)})}\n\n"

        session.commit()
        handler.post_upload(context, [])

        success_count = sum(1 for r in results if r.get('status') == 'success')
        error_count = len(results) - success_count

        # Send completion event
        yield f"data: {json.dumps({'event': 'complete', 'uploaded': success_count, 'errors': error_count, 'results': results})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
