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

import uuid
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.annotation_systems import get_handler, AnnotationContext
from saki_api.api import deps
from saki_api.core.rbac import PermissionChecker
from saki_api.core.rbac.dependencies import (
    get_sample_dataset_id,
    get_permission_checker,
)
from saki_api.db.session import get_session
from saki_api.models import Permissions, ResourceType
from saki_api.models.annotation import Annotation
from saki_api.models.l1.dataset import Dataset
from saki_api.models.enums import AnnotationType, AnnotationSource
from saki_api.models.label import Label
from saki_api.models.l1.sample import Sample, SampleStatus
from saki_api.models.user import User
from saki_api.utils.coordinate_converter import (
    convert_annotation_data_to_backend,
    convert_annotation_data_to_frontend,
)

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
    # Access scope info for frontend UI adaptation
    read_scope: str = "assigned"  # "all", "assigned", or "self"
    modify_scope: str = "assigned"  # "all", "assigned", "self", or "none"


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

def _get_sample_and_dataset(
        session: Session,
        sample_id: str,
) -> tuple[Sample, Dataset]:
    """
    Get and validate sample and its dataset.
    
    Raises:
        HTTPException: If sample or dataset not found
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    dataset = session.get(Dataset, sample.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return sample, dataset


def _get_context(sample: Sample, current_user: Optional[User] = None) -> AnnotationContext:
    """Build annotation context for a sample."""
    return AnnotationContext(
        sample_id=sample.id,
        dataset_id=sample.dataset_id,
        sample_meta=sample.meta_data or {},
        annotator_id=current_user.id if current_user else None,
    )


def _to_item(ann: Annotation, label: Optional[Label] = None) -> AnnotationItem:
    """Convert Annotation model to API response item."""
    annotation_type = ann.type.value if ann.type else AnnotationType.RECT.value

    # 转换数据格式：后端存储（中心点）→ 前端显示（左上角）
    data = convert_annotation_data_to_frontend(annotation_type, ann.data or {})

    return AnnotationItem(
        id=ann.id,
        type=annotation_type,
        source=ann.source.value if ann.source else AnnotationSource.MANUAL.value,
        label_id=ann.label_id,
        label_name=label.name if label else None,
        label_color=label.color if label else None,
        data=data,
        extra=ann.extra or {},
        annotator_id=ann.annotator_id,
    )


def _get_annotation_access_scope(
        session: Session,
        user: User,
        sample_id: str,
        action: str = "read",
        checker: Optional[PermissionChecker] = None,
) -> str:
    """
    Get user's annotation access scope for a sample's dataset.
    
    Uses dependencies.py helper functions to get dataset info.
    Note: owner_id is not needed as dataset_owner role is already set at resource level.
    
    Args:
        session: Database session
        user: Current user
        sample_id: Sample ID
        action: "read" or "modify"
        checker: Optional PermissionChecker instance (for performance)
    
    Returns:
        Access scope: "all", "assigned", "self", or "none"
    """
    if checker is None:
        checker = PermissionChecker(session)

    dataset_id = get_sample_dataset_id(session, sample_id)

    if not dataset_id:
        return "none"

    if action == "read":
        # Check from highest to lowest scope
        # owner_id not needed: dataset_owner role is set at resource level, assigned scope is sufficient
        if checker.check(user.id, Permissions.ANNOTATION_READ_ALL, ResourceType.DATASET, dataset_id):
            return "all"
        if checker.check(user.id, Permissions.ANNOTATION_READ, ResourceType.DATASET, dataset_id):
            return "assigned"
        if checker.check(user.id, Permissions.ANNOTATION_READ_SELF, ResourceType.DATASET, dataset_id):
            return "self"
    else:  # modify
        if checker.check(user.id, Permissions.ANNOTATION_MODIFY_ALL, ResourceType.DATASET, dataset_id):
            return "all"
        if checker.check(user.id, Permissions.ANNOTATION_MODIFY, ResourceType.DATASET, dataset_id):
            return "assigned"
        if checker.check(user.id, Permissions.ANNOTATION_MODIFY_SELF, ResourceType.DATASET, dataset_id):
            return "self"

    return "none"


def _can_access_annotation(
        annotation: Annotation,
        user: User,
        scope: str,
) -> bool:
    """
    Check if user can access a specific annotation based on scope.
    
    Args:
        annotation: The annotation to check
        user: Current user
        scope: Access scope ("all", "assigned", "self")
    
    Returns:
        True if user can access the annotation
    """
    if scope in ("all", "assigned"):
        return True
    if scope == "self":
        # For self scope, user can only access their own annotations
        return annotation.annotator_id == user.id
    return False


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{sample_id}", response_model=SampleAnnotationsResponse)
def get_sample_annotations(
        sample_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Get annotations for a sample.
    
    Returns annotations based on user's access scope:
    - "all" or "assigned": Returns all annotations
    - "self": Returns only user's own annotations (and auto-generated ones)
    """
    sample, dataset = _get_sample_and_dataset(session, sample_id)

    # Check permission and get access scope
    read_scope = _get_annotation_access_scope(session, current_user, sample_id, "read", checker)
    if read_scope == "none":
        raise HTTPException(status_code=403, detail="Permission denied")

    # Query annotations
    statement = select(Annotation).where(Annotation.sample_id == sample_id)
    annotations = session.exec(statement).all()

    # Also get modify scope for frontend
    modify_scope = _get_annotation_access_scope(session, current_user, sample_id, "modify", checker)

    # Filter based on access scope
    items = []
    for ann in annotations:
        if _can_access_annotation(ann, current_user, read_scope):
            label = session.get(Label, ann.label_id)
            items.append(_to_item(ann, label))

    return SampleAnnotationsResponse(
        sample_id=sample_id,
        dataset_id=sample.dataset_id,
        annotation_system=dataset.annotation_system.value,
        annotations=items,
        read_scope=read_scope,
        modify_scope=modify_scope,
    )


@router.post("/sync", response_model=SyncResponse)
def sync_annotations(
        request: SyncRequest,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Sync annotation actions in real-time.
    
    Does NOT persist to database. For FEDO, returns auto-generated
    mapped annotations. Frontend maintains state locally until Save.
    
    Access control:
    - "all" or "assigned": Can modify any annotation
    - "self": Can only modify own annotations (create is always allowed)
    """
    sample, dataset = _get_sample_and_dataset(session, request.sample_id)

    # Check permission and get access scope
    modify_scope = _get_annotation_access_scope(session, current_user, request.sample_id, "modify", checker)
    if modify_scope == "none":
        raise HTTPException(status_code=403, detail="Permission denied")

    context = _get_context(sample, current_user)

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

        # 转换数据格式：前端发送（左上角）→ 后端存储（中心点）
        data = convert_annotation_data_to_backend(ann_type, action.data or {})

        if action.action == "create":
            # Create is always allowed if user has any modify permission
            result = handler.on_annotation_create(
                annotation_id=action.annotation_id,
                label_id=action.label_id or "",
                ann_type=ann_type,
                data=data,
                extra=action.extra or {},
                context=context,
            )

            # 转换生成的标注数据：后端格式（中心点）→ 前端格式（左上角）
            if result.generated:
                result.generated = [
                    {
                        **gen,
                        'data': convert_annotation_data_to_frontend(
                            gen.get('type', ann_type),
                            gen.get('data', {})
                        )
                    }
                    for gen in result.generated
                ]

            results.append(SyncResultItem(
                action="create",
                annotation_id=action.annotation_id,
                success=result.success,
                error=result.error,
                generated=result.generated,
            ))

        elif action.action == "update":
            # For update, check if user can modify this annotation
            existing_ann = session.get(Annotation, action.annotation_id)

            # Check permission for existing annotation (if it exists in DB)
            if existing_ann and not _can_access_annotation(existing_ann, current_user, modify_scope):
                results.append(SyncResultItem(
                    action="update",
                    annotation_id=action.annotation_id,
                    success=False,
                    error="Permission denied: cannot modify other user's annotation",
                ))
                continue

            update_label_id = action.label_id
            update_ann_type = ann_type if action.type else None

            if not update_label_id or not update_ann_type:
                if existing_ann:
                    if not update_label_id:
                        update_label_id = existing_ann.label_id
                    if not update_ann_type:
                        update_ann_type = existing_ann.type
                    if not action.extra and existing_ann.extra:
                        action.extra = existing_ann.extra.copy()
                    elif action.extra and existing_ann.extra:
                        merged_extra = existing_ann.extra.copy()
                        merged_extra.update(action.extra)
                        action.extra = merged_extra

            if not update_ann_type:
                update_ann_type = ann_type

            update_data = convert_annotation_data_to_backend(
                update_ann_type if update_ann_type else ann_type,
                action.data or {}
            ) if action.data else None

            result = handler.on_annotation_update(
                annotation_id=action.annotation_id,
                label_id=update_label_id,
                ann_type=update_ann_type,
                data=update_data,
                extra=action.extra,
                context=context,
            )

            if result.generated:
                result.generated = [
                    {
                        **gen,
                        'data': convert_annotation_data_to_frontend(
                            gen.get('type', update_ann_type.value if update_ann_type else 'rect'),
                            gen.get('data', {})
                        )
                    }
                    for gen in result.generated
                ]

            results.append(SyncResultItem(
                action="update",
                annotation_id=action.annotation_id,
                success=result.success,
                error=result.error,
                generated=result.generated,
            ))

        elif action.action == "delete":
            # For delete, check if user can modify this annotation
            existing_ann = session.get(Annotation, action.annotation_id)

            if existing_ann and not _can_access_annotation(existing_ann, current_user, modify_scope):
                results.append(SyncResultItem(
                    action="delete",
                    annotation_id=action.annotation_id,
                    success=False,
                    error="Permission denied: cannot delete other user's annotation",
                ))
                continue

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
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Batch save annotations for a sample.
    
    Access control behavior:
    - "all" or "assigned": Replaces ALL annotations for the sample
    - "self": Only replaces user's OWN annotations, preserves others' annotations
    
    Note: sample_id is in request body, so we check permission internally.
    """
    sample, dataset = _get_sample_and_dataset(session, request.sample_id)

    # Check permission and get access scope
    modify_scope = _get_annotation_access_scope(session, current_user, request.sample_id, "modify", checker)
    if modify_scope == "none":
        raise HTTPException(status_code=403, detail="Permission denied")

    context = _get_context(sample, current_user)

    # Get handler for pre-save processing
    try:
        handler = get_handler(dataset.annotation_system)
    except ValueError:
        handler = None

    try:
        # Get existing annotations and build a map for quick lookup
        statement = select(Annotation).where(Annotation.sample_id == request.sample_id)
        existing = session.exec(statement).all()
        existing_map = {ann.id: ann for ann in existing}

        # Determine which annotations to delete based on scope
        if modify_scope in ("all", "assigned"):
            # Full access: delete all existing annotations
            for ann in existing:
                session.delete(ann)
        else:  # "self" scope
            # Self scope: only delete user's own annotations (and auto-generated ones)
            for ann in existing:
                if _can_access_annotation(ann, current_user, modify_scope):
                    session.delete(ann)
            # Note: Other users' annotations are preserved

        # Prepare annotations from request
        # 转换数据格式：前端发送（左上角）→ 后端存储（中心点）
        annotations_to_save = []
        for a in request.annotations:
            annotation_type = a.type if isinstance(a.type, str) else a.type.value if a.type else 'rect'
            backend_data = convert_annotation_data_to_backend(annotation_type, a.data or {})

            # For "self" scope, determine the annotator_id from the annotation
            # If the annotation belongs to another user, skip it (don't overwrite)
            if modify_scope == "self":
                # Check if this annotation ID exists and belongs to another user
                existing_ann = existing_map.get(a.id)
                if existing_ann and existing_ann.annotator_id and existing_ann.annotator_id != current_user.id:
                    # This annotation belongs to another user, skip saving it
                    # (It was already preserved above by not deleting it)
                    continue

            # Get original annotator_id from existing annotation if available
            # This ensures we preserve the original creator even if frontend doesn't send it
            original_annotator_id = None
            if a.id in existing_map:
                original_annotator_id = existing_map[a.id].annotator_id
            elif a.annotator_id:
                # Fallback to frontend-provided annotator_id if annotation is new
                original_annotator_id = a.annotator_id

            annotations_to_save.append({
                "id": a.id,
                "sample_id": request.sample_id,
                "label_id": a.label_id,
                "type": a.type,
                "source": a.source,
                "data": backend_data,
                "extra": a.extra,
                "original_annotator_id": original_annotator_id,  # Preserve original annotator from DB
            })

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

            # Determine annotator_id based on source and scope
            source = AnnotationSource(ann_data["source"]) if ann_data.get("source") else AnnotationSource.MANUAL
            annotator_id = None

            # Get original annotator_id from the data (preserved from existing annotation)
            original_annotator = ann_data.get("original_annotator_id")

            if source == AnnotationSource.MANUAL:
                if modify_scope == "self":
                    # In self scope, manual annotations are always owned by current user
                    annotator_id = current_user.id
                else:
                    # In full scope, preserve original annotator if annotation already existed
                    # Only use current_user.id if this is a completely new annotation
                    if original_annotator:
                        # Preserve the original creator
                        annotator_id = original_annotator
                    else:
                        # New annotation created by current user
                        annotator_id = current_user.id
            else:
                # For auto/fedo_mapping source, preserve original annotator if exists
                # Otherwise set to current user (the user who triggered the generation)
                annotator_id = original_annotator if original_annotator else current_user.id

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
        # All users with modify permission can update sample status
        # This allows annotators with "self" scope to mark samples as labeled/skipped
        if request.update_status:
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
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """
    Get a single annotation by ID.
    
    Access control:
    - "all" or "assigned": Can view any annotation
    - "self": Can only view own annotations (and auto-generated ones)
    """
    annotation = session.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Get sample and dataset for permission check
    sample, dataset = _get_sample_and_dataset(session, annotation.sample_id)

    # Check permission and get access scope
    read_scope = _get_annotation_access_scope(session, current_user, sample.id, "read", checker)
    if read_scope == "none":
        raise HTTPException(status_code=403, detail="Permission denied")

    # Check if user can access this specific annotation
    if not _can_access_annotation(annotation, current_user, read_scope):
        raise HTTPException(status_code=403, detail="Permission denied: cannot view other user's annotation")

    label = session.get(Label, annotation.label_id)
    return _to_item(annotation, label)
