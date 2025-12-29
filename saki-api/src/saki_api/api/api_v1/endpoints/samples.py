"""
API endpoints for Sample-level operations including annotations.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlmodel import Session, select

# Import annotation_systems module for handler registry
from saki_api.annotation_systems import (
    get_handler,
    discover_handlers,
    UploadContext,
    ProgressTracker,
)
from saki_api.api import deps
from saki_api.core.config import settings
from saki_api.db.session import get_session
from saki_api.models import (
    Project, )
from saki_api.models.sample import Sample, SampleStatus
from saki_api.models.user import User

logger = logging.getLogger(__name__)

# Initialize handlers on module load
discover_handlers()

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{project_id}", response_model=Dict[str, Any])
def read_samples(
        project_id: str,
        status: Optional[SampleStatus] = None,
        skip: int = 0,
        limit: int = 100,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Get samples for a project.
    """
    query = select(Sample).where(Sample.project_id == project_id)
    if status:
        query = query.where(Sample.status == status)

    # Calculate total count for pagination
    count_query = select(func.count()).where(Sample.project_id == project_id)
    if status:
        count_query = count_query.where(Sample.status == status)
    total = session.exec(count_query).one()

    samples = session.exec(query.offset(skip).limit(limit)).all()

    return {"items": samples, "total": total}


@router.post("/{project_id}/samples")
def upload_samples(
        project_id: str,
        files: List[UploadFile] = File(...),
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Upload samples to a project.
    Uses pluggable handler architecture based on project's annotation system type.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get the appropriate handler for this annotation system
    try:
        handler = get_handler(project.annotation_system)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"No handler available for annotation system: {project.annotation_system.value}"
        )

    upload_dir = Path(settings.UPLOAD_DIR) / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Create upload context
    context = UploadContext(
        project_id=project_id,
        upload_dir=upload_dir,
        project_config={
            'task_type': project.task_type.value if project.task_type else None,
            'labels': project.labels,
        },
        annotation_config=project.annotation_config or {},
    )

    # Initialize progress tracker
    tracker = ProgressTracker(total_files=len(files))

    # Hook: pre-upload
    handler.pre_upload(context)

    results = []

    for index, file in enumerate(files):
        # Log file start
        tracker.file_start(file.filename, index)

        try:
            # Save uploaded file
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # Process file using handler
            result = handler.process_upload(file_path, context)

            if result.success:
                # Create Sample record with handler-specific fields
                sample_fields = handler.get_sample_fields(result)

                sample = Sample(
                    project_id=project_id,
                    file_path=str(file_path),
                    filename=file.filename,
                    status=SampleStatus.UNLABELED,
                    **sample_fields
                )

                # Use sample_id from handler if provided
                if result.sample_id:
                    sample.id = result.sample_id

                session.add(sample)

                tracker.file_complete(file.filename, success=True, sample_id=sample.id)
                results.append({
                    "id": sample.id,
                    "filename": file.filename,
                    "status": "success"
                })
            else:
                tracker.file_complete(file.filename, success=False, error=result.error)
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": result.error
                })

        except Exception as e:
            logger.error(f"Error uploading file {file.filename}: {e}")
            tracker.file_complete(file.filename, success=False, error=str(e))
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })

    session.commit()

    # Hook: post-upload
    handler.post_upload(context, [])

    # Complete tracking
    tracker.complete()

    # Get summary from tracker
    summary = tracker.results

    return {
        "uploaded": summary["success"],
        "errors": summary["errors"],
        "results": results,
        "progress_logs": [log.to_dict() for log in tracker.history]
    }


@router.post("/{project_id}/samples/stream")
async def upload_samples_with_progress(
        project_id: str,
        files: List[UploadFile] = File(...),
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Upload samples with SSE progress streaming.
    Returns a stream of progress events during upload.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        handler = get_handler(project.annotation_system)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"No handler available for annotation system: {project.annotation_system.value}"
        )

    upload_dir = Path(settings.UPLOAD_DIR) / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    context = UploadContext(
        project_id=project_id,
        upload_dir=upload_dir,
        project_config={
            'task_type': project.task_type.value if project.task_type else None,
            'labels': project.labels,
        },
        annotation_config=project.annotation_config or {},
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
                    sample_fields = handler.get_sample_fields(result)
                    sample = Sample(
                        project_id=project_id,
                        file_path=str(file_path),
                        filename=file.filename,
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
