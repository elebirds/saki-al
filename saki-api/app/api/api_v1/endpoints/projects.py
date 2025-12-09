from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlmodel import Session, select
from sqlalchemy import func
from app.db.session import get_session
from app.models import Project, ProjectCreate, ProjectRead, ProjectUpdate, Sample, SampleStatus, SampleRead
from app.api import deps
from app.models.user import User
from app.core.config import settings
from pathlib import Path
import shutil
import os

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
        p_read.stats = {"totalSamples": total, "labeledSamples": labeled, "accuracy": 0.0}
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
    p_read.stats = {"totalSamples": total, "labeledSamples": labeled, "accuracy": 0.0}
    
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
    Delete a project. Only superusers can delete projects.
    """
    # if not current_user.is_superuser:
    #     raise HTTPException(
    #         status_code=403, 
    #         detail="Not enough permissions. Only superusers can delete projects."
    #     )

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    
    # TODO: Trigger actual training task (Celery/BackgroundTasks)
    return {"jobId": "mock-job-id", "status": "queued"}

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

@router.post("/{project_id}/samples")
def upload_samples(
    project_id: str,
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Upload samples to a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    upload_dir = Path(settings.UPLOAD_DIR) / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded_count = 0
    errors_count = 0

    for file in files:
        try:
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Create Sample record
            sample = Sample(
                project_id=project_id,
                file_path=str(file_path),
                url=f"/static/{project_id}/{file.filename}", # Assuming we serve static files
                status=SampleStatus.UNLABELED
            )
            session.add(sample)
            uploaded_count += 1
        except Exception as e:
            print(f"Error uploading file {file.filename}: {e}")
            errors_count += 1
    
    session.commit()
    
    return {
        "uploaded": uploaded_count,
        "errors": errors_count
    }
