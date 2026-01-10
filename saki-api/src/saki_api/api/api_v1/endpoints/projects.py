from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Project, ProjectCreate, ProjectRead, ProjectUpdate, ProjectStats,
    ProjectDataset, ProjectDatasetCreate,
    Sample, SampleStatus, ModelStatus,
    ModelVersion, Dataset
)
from saki_api.models.user import User

router = APIRouter()


def _get_project_stats(session: Session, project: Project) -> ProjectStats:
    """
    Calculate project statistics from linked datasets.
    """
    # Get all dataset IDs linked to this project
    dataset_ids = session.exec(
        select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project.id)
    ).all()

    if not dataset_ids:
        return ProjectStats(total_datasets=0, total_samples=0, labeled_samples=0, accuracy=0.0)

    total_samples = session.exec(
        select(func.count()).select_from(Sample).where(Sample.dataset_id.in_(dataset_ids))
    ).one()

    labeled_samples = session.exec(
        select(func.count()).select_from(Sample).where(
            Sample.dataset_id.in_(dataset_ids),
            Sample.status == SampleStatus.LABELED
        )
    ).one()

    return ProjectStats(
        total_datasets=len(dataset_ids),
        total_samples=total_samples,
        labeled_samples=labeled_samples,
        accuracy=0.0
    )


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
        p_read = ProjectRead.model_validate(p)
        p_read.stats = _get_project_stats(session, p)
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
    db_project = Project.model_validate(project)
    session.add(db_project)
    session.commit()
    session.refresh(db_project)

    p_read = ProjectRead.model_validate(db_project)
    p_read.stats = ProjectStats()
    return p_read


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

    p_read = ProjectRead.model_validate(project)
    p_read.stats = _get_project_stats(session, project)

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

    project_data = project_in.model_dump(exclude_unset=True)
    for key, value in project_data.items():
        setattr(project, key, value)

    session.add(project)
    session.commit()
    session.refresh(project)

    p_read = ProjectRead.model_validate(project)
    p_read.stats = _get_project_stats(session, project)
    return p_read


@router.delete("/{project_id}")
def delete_project(
        project_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Delete a project and its dataset links.
    Note: This does NOT delete the linked datasets or their samples.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete project-dataset links
    links = session.exec(
        select(ProjectDataset).where(ProjectDataset.project_id == project_id)
    ).all()
    for link in links:
        session.delete(link)

    # Delete model versions
    for mv in project.model_versions:
        session.delete(mv)

    # Finally delete the project
    session.delete(project)
    session.commit()
    return {"ok": True, "unlinked_datasets": len(links)}


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


# ============================================================================
# Project-Dataset Link Management
# ============================================================================

@router.get("/{project_id}/datasets")
def get_project_datasets(
        project_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Get all datasets linked to a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get linked datasets with their info
    links = session.exec(
        select(ProjectDataset).where(ProjectDataset.project_id == project_id)
    ).all()

    result = []
    for link in links:
        dataset = session.get(Dataset, link.dataset_id)
        if dataset:
            # Calculate sample stats for this dataset
            sample_count = session.exec(
                select(func.count()).select_from(Sample).where(Sample.dataset_id == dataset.id)
            ).one()
            labeled_count = session.exec(
                select(func.count()).select_from(Sample).where(
                    Sample.dataset_id == dataset.id,
                    Sample.status == SampleStatus.LABELED
                )
            ).one()

            result.append({
                "dataset_id": dataset.id,
                "name": dataset.name,
                "description": dataset.description,
                "annotation_system": dataset.annotation_system.value,
                "sample_count": sample_count,
                "labeled_count": labeled_count,
                "linked_at": link.created_at.isoformat() if link.created_at else None,
            })

    return {"datasets": result, "total": len(result)}


@router.post("/{project_id}/datasets")
def link_dataset_to_project(
        project_id: str,
        link_data: ProjectDatasetCreate,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Link a dataset to a project for use in active learning training.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    dataset = session.get(Dataset, link_data.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check if already linked
    existing = session.exec(
        select(ProjectDataset).where(
            ProjectDataset.project_id == project_id,
            ProjectDataset.dataset_id == link_data.dataset_id
        )
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Dataset already linked to this project")

    # Create link
    link = ProjectDataset(
        project_id=project_id,
        dataset_id=link_data.dataset_id,
    )
    session.add(link)
    session.commit()

    return {"ok": True, "message": f"Dataset '{dataset.name}' linked to project '{project.name}'"}


@router.delete("/{project_id}/datasets/{dataset_id}")
def unlink_dataset_from_project(
        project_id: str,
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Unlink a dataset from a project.
    This does NOT delete the dataset or its samples.
    """
    link = session.exec(
        select(ProjectDataset).where(
            ProjectDataset.project_id == project_id,
            ProjectDataset.dataset_id == dataset_id
        )
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Dataset is not linked to this project")

    session.delete(link)
    session.commit()

    return {"ok": True, "message": "Dataset unlinked from project"}


@router.get("/{project_id}/samples")
def get_project_samples(
        project_id: str,
        status: str = None,
        skip: int = 0,
        limit: int = 100,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Get all samples from datasets linked to a project.
    Useful for active learning to view all available training data.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all dataset IDs linked to this project
    dataset_ids = session.exec(
        select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
    ).all()

    if not dataset_ids:
        return {"items": [], "total": 0}

    # Build query for samples
    query = select(Sample).where(Sample.dataset_id.in_(dataset_ids))
    if status:
        query = query.where(Sample.status == status)

    # Count total
    count_query = select(func.count()).select_from(Sample).where(Sample.dataset_id.in_(dataset_ids))
    if status:
        count_query = count_query.where(Sample.status == status)
    total = session.exec(count_query).one()

    samples = session.exec(query.offset(skip).limit(limit)).all()

    return {"items": samples, "total": total}
