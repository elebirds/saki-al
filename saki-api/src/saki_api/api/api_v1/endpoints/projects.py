from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Project, ProjectCreate, ProjectRead, ProjectUpdate, ProjectStats,
    Sample, SampleStatus, ModelStatus,
    ModelVersion, ModelVersionCreate, ModelVersionRead, ModelVersionUpdate,
)
from saki_api.models.user import User

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
        labeled = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == p.id,
                                                                              Sample.status == SampleStatus.LABELED)).one()
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
    labeled = session.exec(select(func.count()).select_from(Sample).where(Sample.project_id == project.id,
                                                                          Sample.status == SampleStatus.LABELED)).one()
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
    from saki_api.models.annotation import Annotation

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
    version_count = session.exec(
        select(func.count()).select_from(ModelVersion).where(ModelVersion.project_id == project_id)).one()
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
