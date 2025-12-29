"""
API endpoints for Dataset-level operations.
Datasets are independent entities used for data annotation.
"""

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Dataset, DatasetCreate, DatasetRead, DatasetUpdate,
    Sample, SampleStatus,
    Annotation,
)
from saki_api.models.user import User

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
        current_user: User = Depends(deps.get_current_user)
):
    """
    List all datasets with sample statistics.
    """
    datasets = session.exec(select(Dataset).offset(skip).limit(limit)).all()
    result = []
    
    for ds in datasets:
        ds_read = DatasetRead.model_validate(ds)
        
        # Calculate sample statistics
        sample_count = session.exec(
            select(func.count()).select_from(Sample).where(Sample.dataset_id == ds.id)
        ).one()
        labeled_count = session.exec(
            select(func.count()).select_from(Sample).where(
                Sample.dataset_id == ds.id,
                Sample.status == SampleStatus.LABELED
            )
        ).one()
        
        ds_read.sample_count = sample_count
        ds_read.labeled_count = labeled_count
        result.append(ds_read)
    
    return result


@router.post("/", response_model=DatasetRead)
def create_dataset(
        dataset: DatasetCreate,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Create a new dataset for data annotation.
    """
    db_dataset = Dataset.model_validate(dataset)
    session.add(db_dataset)
    session.commit()
    session.refresh(db_dataset)
    
    ds_read = DatasetRead.model_validate(db_dataset)
    ds_read.sample_count = 0
    ds_read.labeled_count = 0
    return ds_read


@router.get("/{dataset_id}", response_model=DatasetRead)
def get_dataset(
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Get dataset by ID with sample statistics.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    ds_read = DatasetRead.model_validate(dataset)
    
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
    
    ds_read.sample_count = sample_count
    ds_read.labeled_count = labeled_count
    
    return ds_read


@router.put("/{dataset_id}", response_model=DatasetRead)
def update_dataset(
        dataset_id: str,
        dataset_in: DatasetUpdate,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
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
    
    return get_dataset(dataset_id, session, current_user)


@router.delete("/{dataset_id}")
def delete_dataset(
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
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
        current_user: User = Depends(deps.get_current_user)
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
    
    return {
        "dataset_id": dataset_id,
        "total_samples": total,
        "labeled_samples": labeled,
        "unlabeled_samples": unlabeled,
        "skipped_samples": skipped,
        "completion_rate": labeled / total if total > 0 else 0.0,
        "linked_projects": project_count,
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
        current_user: User = Depends(deps.get_current_user)
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
                {
                    "id": ann.id,
                    "data": ann.data,
                    "annotator_id": ann.annotator_id,
                    "created_at": ann.created_at.isoformat() if ann.created_at else None,
                }
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
