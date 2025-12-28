from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from sqlalchemy import func
from db.session import get_session
from models import (
    Project, ProjectCreate, ProjectRead, ProjectUpdate, ProjectStats,
    Sample, SampleStatus, SampleRead,
    ModelVersion, ModelVersionCreate, ModelVersionRead, ModelVersionUpdate,
)
from api import deps
from models.user import User
from core.config import settings
from models.enums import ModelStatus, AnnotationSystemType
from pathlib import Path
import shutil
import os
import uuid
import json
import logging

# Import annotation_systems module for handler registry
from annotation_systems import (
    get_handler,
    discover_handlers,
    UploadContext,
    ProgressTracker,
    ProgressLevel,
)

logger = logging.getLogger(__name__)

# Initialize handlers on module load
discover_handlers()


router = APIRouter()

@router.get("/", response_model=List[ProjectRead])
def read_projects(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Retrieve projects.
    """
    projects = session.exec(select(Project).offset(skip).limit(limit)).all()
    result = []
    for p in projects:
        p_read = ProjectRead.from_orm(p)
        total = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == p.id)).one()
        labeled = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == p.id, Sample.status == SampleStatus.LABELED)).one()
        p_read.stats = ProjectStats(totalSamples=total, labeledSamples=labeled, accuracy=0.0)
        result.append(p_read)
    return result

@router.post("/", response_model=ProjectRead)
def create_project(
    project: ProjectCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Create new project.
    """
    db_project = Project.from_orm(project)
    session.add(db_project)
    session.commit()
    session.refresh(db_project)
    return db_project

@router.get("/{project_id}", response_model=ProjectRead)
def read_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get project by ID.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    p_read = ProjectRead.from_orm(project)
    total = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == project.id)).one()
    labeled = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == project.id, Sample.status == SampleStatus.LABELED)).one()
    p_read.stats = ProjectStats(totalSamples=total, labeledSamples=labeled, accuracy=0.0)
    
    return p_read

@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    project_in: ProjectUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Update a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project_data = project_in.dict(exclude_unset=True)
    for key, value in project_data.items():
        setattr(project, key, value)
        
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Delete a project and all related data. Only superusers can delete projects.
    """
    # if not current_user.is_superuser:
    #     raise HTTPException(
    #         status_code=403, 
    #         detail="Not enough permissions. Only superusers can delete projects."
    #     )

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Manually delete related records to avoid foreign key constraint issues
    # Delete model versions
    from models.model_version import ModelVersion
    from models.annotation import Annotation
    
    # Delete annotations for samples in this project
    for sample in project.samples:
        statement = select(Annotation).where(Annotation.sample_id == sample.id)
        annotations = session.exec(statement).all()
        for ann in annotations:
            session.delete(ann)
    
    # Delete samples
    for sample in project.samples:
        session.delete(sample)
    
    # Delete datasets
    for dataset in project.datasets:
        session.delete(dataset)
    
    # Delete model versions
    for mv in project.model_versions:
        session.delete(mv)
    
    # Finally delete the project
    session.delete(project)
    session.commit()
    return {"ok": True}

@router.get("/{project_id}/samples", response_model=Dict[str, Any])
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

@router.post("/{project_id}/train")
def train_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Trigger training for a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Create a new model version entry for tracking the training run.
    version_count = session.exec(select(func.count()).select_from(ModelVersion).where(ModelVersion.project_id == project_id)).one()
    model_version = ModelVersion(
        project_id=project_id,
        base_model_id=project.base_model_id,
        name=f"v{version_count + 1}",
        status=ModelStatus.TRAINING,
        description="Training triggered via /train",
    )
    session.add(model_version)
    session.commit()
    session.refresh(model_version)
    
    # TODO: Trigger actual training task (Celery/BackgroundTasks) and update model_version status/metrics.
    return {"jobId": "mock-job-id", "status": "queued", "modelVersion": model_version}

@router.post("/{project_id}/query", response_model=List[SampleRead])
def query_samples(
    project_id: str,
    n: int = 10,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Query next batch of samples to label.
    """
    # Mock implementation: return random unlabeled samples
    # In real implementation, this would call the AL strategy
    statement = select(Sample).where(
        Sample.project_id == project_id, 
        Sample.status == SampleStatus.UNLABELED
    ).limit(n)
    samples = session.exec(statement).all()
    return samples


@router.get("/{project_id}/models", response_model=List[ModelVersionRead])
def list_model_versions(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    List model versions for a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return session.exec(select(ModelVersion).where(ModelVersion.project_id == project_id)).all()


@router.post("/{project_id}/models", response_model=ModelVersionRead)
def create_model_version(
    project_id: str,
    model_in: ModelVersionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Register a new model version for a project (e.g., external training result).
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = model_in.model_dump()
    payload["project_id"] = project_id  # Enforce path param
    model_version = ModelVersion(**payload)
    session.add(model_version)
    session.commit()
    session.refresh(model_version)
    return model_version


@router.put("/{project_id}/models/{model_id}", response_model=ModelVersionRead)
def update_model_version(
    project_id: str,
    model_id: str,
    model_in: ModelVersionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Update metadata for a model version (metrics, status, weights path, etc.).
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    model_version = session.get(ModelVersion, model_id)
    if not model_version or model_version.project_id != project_id:
        raise HTTPException(status_code=404, detail="Model version not found for project")

    update_data = model_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(model_version, key, value)

    session.add(model_version)
    session.commit()
    session.refresh(model_version)
    return model_version

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

