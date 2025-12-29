from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Project,
    ModelVersion, ModelVersionCreate, ModelVersionRead, ModelVersionUpdate,
)
from saki_api.models.user import User

router = APIRouter()

@router.get("/{project_id}", response_model=List[ModelVersionRead])
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

@router.post("/{project_id}", response_model=ModelVersionRead)
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


@router.put("/{project_id}/{model_id}", response_model=ModelVersionRead)
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
