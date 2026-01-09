"""
API endpoints for Dataset-level operations.

Datasets are independent entities used for data annotation.
Uses the new RBAC system for permission checking.
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api.deps import get_current_user, get_session
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
    PermissionContext,
)
from saki_api.core.rbac.dependencies import get_dataset_owner
from saki_api.core.rbac.presets import get_dataset_owner_role
from saki_api.models import (
    Dataset, DatasetCreate, DatasetRead, DatasetUpdate,
    Sample, SampleStatus,
    Annotation,
    User,
    ResourceMember, ResourceType, RoleType,
    Permissions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Dataset CRUD Endpoints
# ============================================================================

@router.get("/", response_model=List[DatasetRead])
def list_datasets(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    List all datasets with sample statistics.
    
    Automatically filters to only show datasets the user has permission to read:
    - Super admin / Admin: All datasets
    - Regular user: Owned datasets + member datasets
    """
    query = select(Dataset)
    
    # Apply permission-based filtering
    filtered_query = checker.filter_accessible_resources(
        user_id=current_user.id,
        resource_type=ResourceType.DATASET,
        required_permission="dataset:read",
        base_query=query,
        get_owner_id_column=lambda: Dataset.owner_id,
    )
    
    datasets = session.exec(filtered_query.offset(skip).limit(limit)).all()

    result = []
    for ds in datasets:
        ds_read = _build_dataset_read(ds, current_user.id, session, checker)
        result.append(ds_read)

    return result


@router.post("/", response_model=DatasetRead)
def create_dataset(
    dataset: DatasetCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.DATASET_CREATE)),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Create a new dataset for data annotation.
    
    The current user will be set as the owner and automatically
    assigned the dataset_owner role.
    """
    # Create Dataset instance with owner_id from current user
    db_dataset = Dataset(**dataset.model_dump(), owner_id=current_user.id)
    session.add(db_dataset)
    session.flush()  # Get dataset ID
    
    # Assign owner role to creator
    owner_role = get_dataset_owner_role(session)
    if owner_role:
        member = ResourceMember(
            resource_type=ResourceType.DATASET,
            resource_id=db_dataset.id,
            user_id=current_user.id,
            role_id=owner_role.id,
            created_by=current_user.id,
        )
        session.add(member)
    
    session.commit()
    session.refresh(db_dataset)

    return _build_dataset_read(db_dataset, current_user.id, session, checker)


@router.get("/{dataset_id}", response_model=DatasetRead)
def get_dataset(
    dataset_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_READ,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Get dataset by ID with sample statistics.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return _build_dataset_read(dataset, current_user.id, session, checker)


@router.put("/{dataset_id}", response_model=DatasetRead)
def update_dataset(
    dataset_id: str,
    dataset_in: DatasetUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_UPDATE,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Update a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataset_data = dataset_in.model_dump(exclude_unset=True)
    for key, value in dataset_data.items():
        setattr(dataset, key, value)

    session.add(dataset)
    session.commit()
    session.refresh(dataset)

    return _build_dataset_read(dataset, current_user.id, session, checker)


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_DELETE,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Delete a dataset and all its samples and annotations.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check if dataset is linked to any projects
    from saki_api.models import ProjectDataset
    project_links = session.exec(
        select(ProjectDataset).where(ProjectDataset.dataset_id == dataset_id)
    ).all()

    if project_links:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset is linked to {len(project_links)} project(s). Unlink first before deleting."
        )

    # Delete all annotations for samples in this dataset
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    for sample in samples:
        annotations = session.exec(
            select(Annotation).where(Annotation.sample_id == sample.id)
        ).all()
        for ann in annotations:
            session.delete(ann)
        session.delete(sample)

    # Delete resource members
    members = session.exec(
        select(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id
        )
    ).all()
    for member in members:
        session.delete(member)

    # Delete the dataset
    session.delete(dataset)
    session.commit()

    return {"ok": True, "deleted_samples": len(samples)}


# ============================================================================
# Dataset Statistics Endpoints
# ============================================================================

@router.get("/{dataset_id}/stats")
def get_dataset_stats(
    dataset_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_READ,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    ))
) -> Dict[str, Any]:
    """
    Get detailed statistics for a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Sample counts by status
    total = session.exec(
        select(func.count()).select_from(Sample).where(Sample.dataset_id == dataset_id)
    ).one()

    labeled = session.exec(
        select(func.count()).select_from(Sample).where(
            Sample.dataset_id == dataset_id,
            Sample.status == SampleStatus.LABELED
        )
    ).one()

    unlabeled = session.exec(
        select(func.count()).select_from(Sample).where(
            Sample.dataset_id == dataset_id,
            Sample.status == SampleStatus.UNLABELED
        )
    ).one()

    skipped = session.exec(
        select(func.count()).select_from(Sample).where(
            Sample.dataset_id == dataset_id,
            Sample.status == SampleStatus.SKIPPED
        )
    ).one()

    # Count linked projects
    from saki_api.models import ProjectDataset
    project_count = session.exec(
        select(func.count()).select_from(ProjectDataset).where(
            ProjectDataset.dataset_id == dataset_id
        )
    ).one()

    # Count members
    member_count = session.exec(
        select(func.count()).select_from(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id
        )
    ).one()

    return {
        "dataset_id": dataset_id,
        "total_samples": total,
        "labeled_samples": labeled,
        "unlabeled_samples": unlabeled,
        "skipped_samples": skipped,
        "completion_rate": labeled / total if total > 0 else 0.0,
        "linked_projects": project_count,
        "member_count": member_count,
    }


# ============================================================================
# Dataset Export Endpoints
# ============================================================================

@router.get("/{dataset_id}/export")
def export_dataset(
    dataset_id: str,
    format: str = "json",
    include_unlabeled: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_EXPORT,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    ))
) -> Dict[str, Any]:
    """
    Export dataset annotations in various formats.
    
    Args:
        dataset_id: ID of the dataset to export
        format: Export format (json, coco, yolo, csv)
        include_unlabeled: Whether to include unlabeled samples
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Build sample query
    query = select(Sample).where(Sample.dataset_id == dataset_id)
    if not include_unlabeled:
        query = query.where(Sample.status == SampleStatus.LABELED)

    samples = session.exec(query).all()

    # Get annotations for each sample
    export_data = []
    for sample in samples:
        annotations = session.exec(
            select(Annotation).where(Annotation.sample_id == sample.id)
        ).all()

        export_data.append({
            "sample_id": sample.id,
            "name": sample.name,
            "url": sample.url,
            "status": sample.status.value,
            "meta_data": sample.meta_data,
            "annotations": [
                ann.model_dump(exclude={"sample_id"})
                for ann in annotations
            ]
        })

    # TODO: Implement other export formats (COCO, YOLO, CSV)
    if format != "json":
        raise HTTPException(
            status_code=400,
            detail=f"Export format '{format}' not yet implemented. Use 'json'."
        )

    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "annotation_system": dataset.annotation_system.value,
        },
        "samples": export_data,
        "total": len(export_data),
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _build_dataset_read(
    dataset: Dataset,
    user_id: str,
    session: Session,
    checker: PermissionChecker
) -> DatasetRead:
    """Build DatasetRead with statistics and user role."""
    # Calculate sample statistics
    sample_count = session.exec(
        select(func.count()).select_from(Sample).where(Sample.dataset_id == dataset.id)
    ).one()
    labeled_count = session.exec(
        select(func.count()).select_from(Sample).where(
            Sample.dataset_id == dataset.id,
            Sample.status == SampleStatus.LABELED
        )
    ).one()

    # Get user's role in this dataset
    user_role = None
    role = checker.get_user_role_in_resource(
        user_id, ResourceType.DATASET, dataset.id
    )
    if role:
        user_role = role.name

    return DatasetRead(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        annotation_system=dataset.annotation_system,
        owner_id=dataset.owner_id,
        created_at=str(dataset.created_at),
        updated_at=str(dataset.updated_at),
        sample_count=sample_count,
        labeled_count=labeled_count,
        user_role=user_role,
    )
