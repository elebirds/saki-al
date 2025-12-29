"""
API endpoints for Label operations.
Labels belong to Datasets and are used for annotation.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Label, LabelCreate, LabelRead, LabelUpdate,
    Dataset, Annotation,
)
from saki_api.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Label CRUD Endpoints
# ============================================================================

@router.get("/{dataset_id}/labels", response_model=List[LabelRead])
def list_labels(
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    List all labels for a dataset with annotation counts.
    """
    # Verify dataset exists
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Get labels with annotation counts
    labels = session.exec(
        select(Label)
        .where(Label.dataset_id == dataset_id)
        .order_by(Label.sort_order, Label.created_at)
    ).all()
    
    result = []
    for label in labels:
        label_read = LabelRead.model_validate(label)
        # Count annotations using this label
        annotation_count = session.exec(
            select(func.count()).select_from(Annotation).where(Annotation.label_id == label.id)
        ).one()
        label_read.annotation_count = annotation_count
        result.append(label_read)
    
    return result


@router.post("/{dataset_id}/labels", response_model=LabelRead)
def create_label(
        dataset_id: str,
        label_in: LabelCreate,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Create a new label for a dataset.
    """
    # Verify dataset exists
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Check for duplicate name in this dataset
    existing = session.exec(
        select(Label).where(
            Label.dataset_id == dataset_id,
            Label.name == label_in.name
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=400, 
            detail=f"Label with name '{label_in.name}' already exists in this dataset"
        )
    
    # Create the label
    db_label = Label(
        dataset_id=dataset_id,
        **label_in.model_dump()
    )
    session.add(db_label)
    session.commit()
    session.refresh(db_label)
    
    label_read = LabelRead.model_validate(db_label)
    label_read.annotation_count = 0
    return label_read


@router.get("/labels/{label_id}", response_model=LabelRead)
def get_label(
        label_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Get a label by ID.
    """
    label = session.get(Label, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    
    label_read = LabelRead.model_validate(label)
    # Count annotations
    annotation_count = session.exec(
        select(func.count()).select_from(Annotation).where(Annotation.label_id == label.id)
    ).one()
    label_read.annotation_count = annotation_count
    
    return label_read


@router.put("/labels/{label_id}", response_model=LabelRead)
def update_label(
        label_id: str,
        label_in: LabelUpdate,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Update a label (name, color, etc.).
    This is safe because annotations reference by label_id, not name.
    """
    label = session.get(Label, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    
    # Check for duplicate name if name is being changed
    update_data = label_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] != label.name:
        existing = session.exec(
            select(Label).where(
                Label.dataset_id == label.dataset_id,
                Label.name == update_data["name"],
                Label.id != label_id
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Label with name '{update_data['name']}' already exists in this dataset"
            )
    
    # Update fields
    for key, value in update_data.items():
        setattr(label, key, value)
    
    session.add(label)
    session.commit()
    session.refresh(label)
    
    label_read = LabelRead.model_validate(label)
    annotation_count = session.exec(
        select(func.count()).select_from(Annotation).where(Annotation.label_id == label.id)
    ).one()
    label_read.annotation_count = annotation_count
    
    return label_read


@router.delete("/labels/{label_id}")
def delete_label(
        label_id: str,
        force: bool = Query(False, description="Force delete even if label has annotations"),
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Delete a label.
    
    If the label has annotations:
    - Without force=True: Returns 409 Conflict with annotation count
    - With force=True: Deletes label and all associated annotations
    """
    label = session.get(Label, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    
    # Count annotations using this label
    annotation_count = session.exec(
        select(func.count()).select_from(Annotation).where(Annotation.label_id == label.id)
    ).one()
    
    if annotation_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Label '{label.name}' has {annotation_count} annotation(s). Use force=true to delete anyway.",
                "annotation_count": annotation_count,
                "require_confirmation": True
            }
        )
    
    # Delete associated annotations if any
    if annotation_count > 0:
        annotations = session.exec(
            select(Annotation).where(Annotation.label_id == label.id)
        ).all()
        for ann in annotations:
            session.delete(ann)
    
    # Delete the label
    session.delete(label)
    session.commit()
    
    return {
        "ok": True,
        "deleted_label": label.name,
        "deleted_annotations": annotation_count
    }


# ============================================================================
# Batch Operations
# ============================================================================

@router.post("/{dataset_id}/labels/batch", response_model=List[LabelRead])
def create_labels_batch(
        dataset_id: str,
        labels_in: List[LabelCreate],
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Create multiple labels at once for a dataset.
    """
    # Verify dataset exists
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Get existing label names
    existing_names = set(
        session.exec(
            select(Label.name).where(Label.dataset_id == dataset_id)
        ).all()
    )
    
    result = []
    for i, label_in in enumerate(labels_in):
        if label_in.name in existing_names:
            continue  # Skip duplicates
        
        db_label = Label(
            dataset_id=dataset_id,
            sort_order=label_in.sort_order if label_in.sort_order else i,
            **label_in.model_dump(exclude={"sort_order"})
        )
        session.add(db_label)
        existing_names.add(label_in.name)
        result.append(db_label)
    
    session.commit()
    
    # Refresh and return
    label_reads = []
    for label in result:
        session.refresh(label)
        label_read = LabelRead.model_validate(label)
        label_read.annotation_count = 0
        label_reads.append(label_read)
    
    return label_reads
