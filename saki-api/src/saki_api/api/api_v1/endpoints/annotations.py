"""
API endpoints for annotation operations in sample-level.
"""

from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.db.session import get_session
from saki_api.models.annotation import Annotation
from saki_api.models.sample import Sample, SampleStatus

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AnnotationData(BaseModel):
    """Single annotation item as sent from frontend."""
    id: str
    type: str  # 'bbox', 'obb', 'polygon', etc.
    label: str
    color: str
    bbox: Optional[Dict[str, float]] = None  # {x, y, width, height, rotation}
    points: Optional[List[List[float]]] = None  # For polygon/polyline


class AnnotationPayload(BaseModel):
    """Request payload for saving annotations."""
    data: List[AnnotationData]
    status: Optional[str] = 'labeled'


class AnnotationResponse(BaseModel):
    """Response with annotations for a sample."""
    sample_id: str
    data: List[AnnotationData]


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
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    # Query annotations for this sample
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    annotations = session.exec(statement).all()

    # Combine all annotation data
    # Each Annotation record may contain multiple annotation items in its `data` field
    all_data: List[AnnotationData] = []
    for ann in annotations:
        if isinstance(ann.data, list):
            for item in ann.data:
                all_data.append(AnnotationData(**item))
        elif isinstance(ann.data, dict) and 'annotations' in ann.data:
            for item in ann.data['annotations']:
                all_data.append(AnnotationData(**item))

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
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    # Delete existing annotations for this sample
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    existing = session.exec(statement).all()
    for ann in existing:
        session.delete(ann)

    # Create new annotation record with all items
    if payload.data:
        new_annotation = Annotation(
            sample_id=sample_id,
            data=[item.model_dump() for item in payload.data],
        )
        session.add(new_annotation)

    # Update sample status
    if payload.status == 'labeled':
        sample.status = SampleStatus.LABELED
    elif payload.status == 'skipped':
        sample.status = SampleStatus.SKIPPED

    session.commit()

    return AnnotationResponse(sample_id=sample_id, data=payload.data)
