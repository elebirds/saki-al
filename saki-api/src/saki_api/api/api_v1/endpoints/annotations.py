"""
API endpoints for annotation operations in sample-level.
Each annotation item is stored as a separate Annotation record with a label_id reference.
"""

from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.db.session import get_session
from saki_api.models.annotation import Annotation
from saki_api.models.sample import Sample, SampleStatus
from saki_api.models.label import Label

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AnnotationData(BaseModel):
    """Single annotation item as sent from frontend."""
    id: str
    type: str  # 'bbox', 'obb', 'polygon', etc.
    labelId: str  # Reference to Label.id
    bbox: Optional[Dict[str, float]] = None  # {x, y, width, height, rotation}
    points: Optional[List[List[float]]] = None  # For polygon/polyline


class AnnotationDataResponse(BaseModel):
    """Single annotation item with label info for response."""
    id: str
    type: str
    labelId: str
    labelName: str
    labelColor: str
    bbox: Optional[Dict[str, float]] = None
    points: Optional[List[List[float]]] = None


class AnnotationPayload(BaseModel):
    """Request payload for saving annotations."""
    data: List[AnnotationData]
    status: Optional[str] = 'labeled'


class AnnotationResponse(BaseModel):
    """Response with annotations for a sample."""
    sample_id: str
    data: List[AnnotationDataResponse]


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{sample_id}", response_model=AnnotationResponse)
def get_annotations(
        sample_id: str,
        session: Session = Depends(get_session),
):
    """
    Get all annotations for a sample.
    Each annotation record represents a single annotation item.
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    # Query annotations for this sample
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    annotations = session.exec(statement).all()

    # Build response with label info
    all_data: List[AnnotationDataResponse] = []
    for ann in annotations:
        # Get label info
        label = session.get(Label, ann.label_id)
        if not label:
            continue  # Skip orphaned annotations
        
        # Extract bbox/points from data field
        ann_data = ann.data or {}
        
        all_data.append(AnnotationDataResponse(
            id=ann.id,
            type=ann_data.get('type', 'rect'),
            labelId=ann.label_id,
            labelName=label.name,
            labelColor=label.color,
            bbox=ann_data.get('bbox'),
            points=ann_data.get('points'),
        ))

    return AnnotationResponse(sample_id=sample_id, data=all_data)


@router.post("/{sample_id}", response_model=AnnotationResponse)
def save_sample_annotations(
        sample_id: str,
        payload: AnnotationPayload,
        session: Session = Depends(get_session),
):
    """
    Save annotations for a sample.
    This replaces any existing annotations.
    Each annotation item becomes a separate Annotation record.
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    # Delete existing annotations for this sample
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    existing = session.exec(statement).all()
    for ann in existing:
        session.delete(ann)

    # Create new annotation records - one per annotation item
    response_data: List[AnnotationDataResponse] = []
    
    for item in payload.data:
        # Verify label exists
        label = session.get(Label, item.labelId)
        if not label:
            raise HTTPException(
                status_code=400, 
                detail=f"Label with id '{item.labelId}' not found"
            )
        
        # Store geometry data in the data field
        data_dict = {
            'type': item.type,
        }
        if item.bbox:
            data_dict['bbox'] = item.bbox
        if item.points:
            data_dict['points'] = item.points
        
        new_annotation = Annotation(
            id=item.id,  # Use the frontend-provided ID for consistency
            sample_id=sample_id,
            label_id=item.labelId,
            data=data_dict,
        )
        session.add(new_annotation)
        
        response_data.append(AnnotationDataResponse(
            id=item.id,
            type=item.type,
            labelId=item.labelId,
            labelName=label.name,
            labelColor=label.color,
            bbox=item.bbox,
            points=item.points,
        ))

    # Update sample status
    if payload.status == 'labeled':
        sample.status = SampleStatus.LABELED
    elif payload.status == 'skipped':
        sample.status = SampleStatus.SKIPPED

    session.commit()

    return AnnotationResponse(sample_id=sample_id, data=response_data)
