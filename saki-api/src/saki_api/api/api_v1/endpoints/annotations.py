"""
Annotation API endpoints.

Provides:
1. GET /{sample_id} - Get all annotations for a sample
2. POST /sync - Real-time sync during annotation session
3. POST /save - Batch save annotations when user clicks Save

Workflow:
1. User opens sample for annotation
2. Each create/update/delete action syncs via POST /sync
3. For FEDO: sync returns auto-generated mapped annotations
4. User clicks Save → POST /save persists to database
"""

from typing import List, Optional, Dict, Any
import uuid

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models.annotation import Annotation
from saki_api.models.sample import Sample, SampleStatus
from saki_api.models.dataset import Dataset
from saki_api.models.label import Label
from saki_api.models.user import User
from saki_api.models.enums import AnnotationType, AnnotationSource
from saki_api.models.permission import Permission
from saki_api.core.permissions import require_permission
from saki_api.annotation_systems import get_handler, AnnotationContext

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AnnotationItem(BaseModel):
    """Single annotation item."""
    id: str
    type: str  # AnnotationType value
    source: str = "manual"  # AnnotationSource value
    label_id: str
    label_name: Optional[str] = None
    label_color: Optional[str] = None
    data: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}  # System-specific (e.g., parent_id, view for FEDO)
    annotator_id: Optional[str] = None  # ID of the user who created the annotation


class SampleAnnotationsResponse(BaseModel):
    """Response with all annotations for a sample."""
    sample_id: str
    dataset_id: str
    annotation_system: str
    annotations: List[AnnotationItem]


class SyncActionRequest(BaseModel):
    """Single sync action from frontend."""
    action: str  # 'create', 'update', 'delete'
    annotation_id: str
    label_id: Optional[str] = None
    type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class SyncRequest(BaseModel):
    """Sync request with multiple actions."""
    sample_id: str
    actions: List[SyncActionRequest]


class SyncResultItem(BaseModel):
    """Result of a single sync action."""
    action: str
    annotation_id: str
    success: bool
    error: Optional[str] = None
    generated: List[Dict[str, Any]] = []  # Auto-generated annotations


class SyncResponse(BaseModel):
    """Response for sync request."""
    sample_id: str
    results: List[SyncResultItem]
    ready: bool = True


class BatchSaveRequest(BaseModel):
    """Request for batch saving annotations."""
    sample_id: str
    annotations: List[AnnotationItem]
    update_status: Optional[str] = None  # 'labeled', 'skipped', None


class BatchSaveResponse(BaseModel):
    """Response for batch save."""
    sample_id: str
    saved_count: int
    success: bool
    error: Optional[str] = None


# ============================================================================
# Helpers
# ============================================================================

def _get_context(sample: Sample, session: Session, current_user: Optional[User] = None) -> AnnotationContext:
    """Build annotation context for a sample."""
    dataset = session.get(Dataset, sample.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    return AnnotationContext(
        sample_id=sample.id,
        dataset_id=sample.dataset_id,
        sample_meta=sample.meta_data or {},
        annotator_id=current_user.id if current_user else None,
    )


def _to_item(ann: Annotation, label: Optional[Label] = None) -> AnnotationItem:
    """Convert Annotation model to API response item."""
    return AnnotationItem(
        id=ann.id,
        type=ann.type.value if ann.type else AnnotationType.RECT.value,
        source=ann.source.value if ann.source else AnnotationSource.MANUAL.value,
        label_id=ann.label_id,
        label_name=label.name if label else None,
        label_color=label.color if label else None,
        data=ann.data or {},
        extra=ann.extra or {},
        annotator_id=ann.annotator_id,
    )


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{sample_id}", response_model=SampleAnnotationsResponse)
def get_sample_annotations(
    sample_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permission.ANNOTATION_READ, "sample", "sample_id"
    )),
):
    """Get all annotations for a sample."""
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    dataset = session.get(Dataset, sample.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Query annotations
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    annotations = session.exec(statement).all()
    
    # Build response with label info
    items = []
    for ann in annotations:
        label = session.get(Label, ann.label_id)
        items.append(_to_item(ann, label))
    
    return SampleAnnotationsResponse(
        sample_id=sample_id,
        dataset_id=sample.dataset_id,
        annotation_system=dataset.annotation_system.value,
        annotations=items,
    )


@router.post("/sync", response_model=SyncResponse)
def sync_annotations(
    request: SyncRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Sync annotation actions in real-time.
    
    Does NOT persist to database. For FEDO, returns auto-generated
    mapped annotations. Frontend maintains state locally until Save.
    """
    # Check permission for the sample
    from saki_api.core.permissions import check_permission
    if not check_permission(
        current_user, Permission.ANNOTATION_MODIFY, "sample", request.sample_id, session
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    sample = session.get(Sample, request.sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    dataset = session.get(Dataset, sample.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    context = _get_context(sample, session, current_user)
    
    # Get handler for this annotation system
    try:
        handler = get_handler(dataset.annotation_system)
    except ValueError:
        # Fallback to classic (pass-through)
        from saki_api.annotation_systems.handlers.classic import ClassicHandler
        handler = ClassicHandler()
    
    results: List[SyncResultItem] = []
    
    for action in request.actions:
        ann_type = AnnotationType(action.type) if action.type else AnnotationType.RECT
        
        if action.action == "create":
            result = handler.on_annotation_create(
                annotation_id=action.annotation_id,
                label_id=action.label_id or "",
                ann_type=ann_type,
                data=action.data or {},
                extra=action.extra or {},
                context=context,
            )
            
            results.append(SyncResultItem(
                action="create",
                annotation_id=action.annotation_id,
                success=result.success,
                error=result.error,
                generated=result.generated,
            ))
        
        elif action.action == "update":
            # For update, if label_id or type is missing, try to get from existing annotation
            update_label_id = action.label_id
            update_ann_type = ann_type if action.type else None
            
            if not update_label_id or not update_ann_type:
                # Try to get from existing annotation in database
                existing_ann = session.get(Annotation, action.annotation_id)
                if existing_ann:
                    if not update_label_id:
                        update_label_id = existing_ann.label_id
                    if not update_ann_type:
                        update_ann_type = existing_ann.type
                    # Also merge extra data if not provided
                    if not action.extra and existing_ann.extra:
                        action.extra = existing_ann.extra.copy()
                    elif action.extra and existing_ann.extra:
                        # Merge extra data, with action.extra taking precedence
                        merged_extra = existing_ann.extra.copy()
                        merged_extra.update(action.extra)
                        action.extra = merged_extra
            
            result = handler.on_annotation_update(
                annotation_id=action.annotation_id,
                label_id=update_label_id,
                ann_type=update_ann_type,
                data=action.data,
                extra=action.extra,
                context=context,
            )
            
            results.append(SyncResultItem(
                action="update",
                annotation_id=action.annotation_id,
                success=result.success,
                error=result.error,
                generated=result.generated,
            ))
        
        elif action.action == "delete":
            result = handler.on_annotation_delete(
                annotation_id=action.annotation_id,
                extra=action.extra or {},
                context=context,
            )
            
            results.append(SyncResultItem(
                action="delete",
                annotation_id=action.annotation_id,
                success=result.success,
                error=result.error,
                generated=result.generated,
            ))
        
        else:
            results.append(SyncResultItem(
                action=action.action,
                annotation_id=action.annotation_id,
                success=False,
                error=f"Unknown action: {action.action}",
            ))
    
    return SyncResponse(
        sample_id=request.sample_id,
        results=results,
        ready=True,
    )


@router.post("/save", response_model=BatchSaveResponse)
def save_annotations(
    request: BatchSaveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Batch save all annotations for a sample.
    
    Replaces existing annotations. Called when user clicks Save.
    """
    # Check permission for the sample
    from saki_api.core.permissions import check_permission
    if not check_permission(
        current_user, Permission.ANNOTATION_MODIFY, "sample", request.sample_id, session
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    sample = session.get(Sample, request.sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    dataset = session.get(Dataset, sample.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    context = _get_context(sample, session, current_user)
    
    # Get handler for pre-save processing
    try:
        handler = get_handler(dataset.annotation_system)
    except ValueError:
        handler = None
    
    try:
        # Delete existing annotations
        statement = select(Annotation).where(Annotation.sample_id == request.sample_id)
        existing = session.exec(statement).all()
        for ann in existing:
            session.delete(ann)
        
        # Prepare annotations
        # 注意：annotator_id 由后端自动设置，不从请求中读取
        annotations_to_save = [
            {
                "id": a.id,
                "sample_id": request.sample_id,
                "label_id": a.label_id,
                "type": a.type,
                "source": a.source,
                "data": a.data,
                "extra": a.extra,
            }
            for a in request.annotations
        ]
        
        # Pre-save hook
        if handler:
            annotations_to_save = handler.on_batch_save(annotations_to_save, context)
        
        # Create annotation records
        saved_count = 0
        for ann_data in annotations_to_save:
            # Verify label exists
            label = session.get(Label, ann_data["label_id"])
            if not label:
                raise HTTPException(
                    status_code=400,
                    detail=f"Label '{ann_data['label_id']}' not found"
                )
            
            # 根据source设置annotator_id：
            # - manual标注：使用当前用户ID
            # - auto/fedo_mapping标注：设置为None（系统自动生成）
            source = AnnotationSource(ann_data["source"]) if ann_data.get("source") else AnnotationSource.MANUAL
            annotator_id = None
            if source == AnnotationSource.MANUAL and current_user:
                annotator_id = current_user.id
            
            new_ann = Annotation(
                id=ann_data.get("id") or str(uuid.uuid4()),
                sample_id=request.sample_id,
                label_id=ann_data["label_id"],
                type=AnnotationType(ann_data["type"]) if ann_data.get("type") else AnnotationType.RECT,
                source=source,
                data=ann_data.get("data") or {},
                extra=ann_data.get("extra") or {},
                annotator_id=annotator_id,
            )
            session.add(new_ann)
            saved_count += 1
        
        # Update sample status
        if request.update_status == 'labeled':
            sample.status = SampleStatus.LABELED
        elif request.update_status == 'skipped':
            sample.status = SampleStatus.SKIPPED
        
        session.commit()
        
        return BatchSaveResponse(
            sample_id=request.sample_id,
            saved_count=saved_count,
            success=True,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        return BatchSaveResponse(
            sample_id=request.sample_id,
            saved_count=0,
            success=False,
            error=str(e),
        )


@router.get("/detail/{annotation_id}", response_model=AnnotationItem)
def get_annotation(
    annotation_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user),
):
    """Get a single annotation by ID."""
    annotation = session.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    
    # Check permission through sample
    from saki_api.core.permissions import check_permission
    if not check_permission(
        current_user, Permission.ANNOTATION_READ, "sample", annotation.sample_id, session
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    label = session.get(Label, annotation.label_id)
    return _to_item(annotation, label)

