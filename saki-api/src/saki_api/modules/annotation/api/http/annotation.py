"""
Annotation Endpoints.
"""

import uuid
from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Depends, Query

from saki_api.app.deps import (
    AnnotationServiceDep,
    ProjectServiceDep,
    AnnotationDraftServiceDep,
    AnnotationWorkingServiceDep,
    AnnotationSyncServiceDep,
    DatasetServiceDep,
    SampleServiceDep,
)
from saki_api.core.exceptions import ConflictAppException
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.annotation.api.annotation import AnnotationCreate, AnnotationHistoryItem, AnnotationRead
from saki_api.modules.annotation.api.draft import (
    AnnotationDraftCommitRequest,
    AnnotationDraftRead,
    AnnotationDraftUpsert,
    AnnotationWorkingUpsert,
)
from saki_api.modules.annotation.api.sync import AnnotationSyncRequest, AnnotationSyncResponse
from saki_api.modules.annotation.domain.coordinate_converter import convert_annotation_item_to_frontend, \
    convert_annotation_data_to_frontend
from saki_api.modules.annotation.extensions.factory import AnnotationSystemFactory
from saki_api.modules.annotation.extensions.sync.base import AnnotationContext
from saki_api.modules.access.domain.rbac import Permissions, ResourceType

router = APIRouter()


def _normalize_type(annotation_type: object) -> str:
    if hasattr(annotation_type, "value"):
        return annotation_type.value
    return str(annotation_type)


def _to_annotation_read(annotation) -> AnnotationRead:
    payload = annotation.model_dump()
    payload["data"] = convert_annotation_data_to_frontend(
        _normalize_type(payload.get("type")),
        payload.get("data"),
    )
    return AnnotationRead.model_validate(payload)


def _convert_payload_to_frontend(payload: dict) -> dict:
    annotations = payload.get("annotations") or []
    converted = [convert_annotation_item_to_frontend(item) for item in annotations]
    return {
        "annotations": converted,
        "meta": payload.get("meta") or {},
    }


# =============================================================================
# Annotation CRUD Endpoints
# =============================================================================


@router.get("/commits/{commit_id}/annotations", response_model=List[AnnotationRead], dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def get_annotations_at_commit(
        *,
        commit_id: uuid.UUID,
        sample_id: uuid.UUID | None = None,
        annotation_service: AnnotationServiceDep,
):
    """
    Get annotations for a specific commit.

    Optionally filter by sample_id to get annotations for a specific sample.
    """
    annotations = await annotation_service.get_annotations_at_commit(commit_id, sample_id)
    return [_to_annotation_read(a) for a in annotations]


@router.get("/samples/{sample_id}/annotations", response_model=List[AnnotationRead], dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def get_sample_annotations(
        *,
        sample_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Get all annotations for a sample (all versions).

    Returns all annotations across all commits for this sample.
    """
    annotations = await annotation_service.get_sample_annotations(sample_id)
    return [_to_annotation_read(a) for a in annotations]


@router.get("/projects/{project_id}/annotations", response_model=List[AnnotationRead], dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ, ResourceType.PROJECT, "project_id"))
])
async def get_project_annotations(
        *,
        project_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Get all annotations for a project.
    """
    annotations = await annotation_service.get_project_annotations(project_id)
    return [_to_annotation_read(a) for a in annotations]


@router.get("/annotations/{annotation_id}", response_model=AnnotationRead, dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def get_annotation(
        *,
        annotation_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Get an annotation by ID.
    """
    annotation = await annotation_service.get_by_id_or_raise(annotation_id)
    return _to_annotation_read(annotation)


@router.get("/annotations/{annotation_id}/history", response_model=List[AnnotationHistoryItem],
            dependencies=[
                Depends(require_permission(Permissions.ANNOTATION_READ))
            ])
async def get_annotation_history(
        *,
        annotation_id: uuid.UUID,
        depth: int = 100,
        annotation_service: AnnotationServiceDep,
):
    """
    Get annotation modification history by following parent_id chain.

    Returns annotations from oldest to newest.
    """
    return await annotation_service.get_annotation_history(annotation_id, depth)


@router.post("/annotations", response_model=AnnotationRead, dependencies=[
    Depends(require_permission(Permissions.ANNOTATE))
])
async def create_annotation(
        *,
        annotation_in: AnnotationCreate,
        annotation_service: AnnotationServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Create a new annotation.

    For modifications, include parent_id to reference the annotation being modified.
    The new annotation will be immutable - further modifications create additional records.
    """
    # Set annotator to current user if not provided
    if not annotation_in.annotator_id:
        annotation_in.annotator_id = current_user_id

    annotation = await annotation_service.create_annotation(annotation_in)
    return AnnotationRead.model_validate(annotation)


@router.post("/projects/{project_id}/samples/{sample_id}/sync", response_model=AnnotationSyncResponse, dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def sync_annotation(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        sync_in: AnnotationSyncRequest,
        annotation_sync_service: AnnotationSyncServiceDep,
        dataset_service: DatasetServiceDep,
        sample_service: SampleServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Full snapshot sync with auto-promotion and incremental updates.
    """
    sample = await sample_service.get_by_id_or_raise(sample_id)
    dataset = await dataset_service.get_by_id_or_raise(sample.dataset_id)

    facade = AnnotationSystemFactory.create_system(dataset.type, sample_service.session)
    context = AnnotationContext(
        sample_id=str(sample_id),
        dataset_id=str(sample.dataset_id),
        project_id=str(project_id),
        sample_meta=sample.meta_info or {},
        annotator_id=str(current_user_id),
    )

    snapshot = await annotation_sync_service.get_or_promote_snapshot(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=sync_in.branch_name,
    )

    base_commit_id = snapshot.get("base_commit_id")
    current_seq = int(snapshot.get("seq") or 0)
    payload = _convert_payload_to_frontend({
        "annotations": snapshot.get("annotations") or [],
        "meta": snapshot.get("meta") or {},
    })

    if sync_in.base_commit_id and base_commit_id:
        if str(sync_in.base_commit_id) != str(base_commit_id):
            conflict_payload = AnnotationSyncResponse(
                status="conflict",
                current_seq_id=current_seq,
                base_commit_id=uuid.UUID(base_commit_id) if base_commit_id else None,
                payload=payload,
            )
            raise ConflictAppException(
                "Base commit mismatch",
                data=conflict_payload.model_dump(mode="json"),
            )

    if sync_in.last_seq_id != current_seq:
        conflict_payload = AnnotationSyncResponse(
            status="conflict",
            current_seq_id=current_seq,
            base_commit_id=uuid.UUID(base_commit_id) if base_commit_id else None,
            payload=payload,
        )
        raise ConflictAppException(
            "Sequence mismatch",
            data=conflict_payload.model_dump(mode="json"),
        )

    if not sync_in.actions and sync_in.meta is None:
        return AnnotationSyncResponse(
            status="success",
            current_seq_id=current_seq,
            base_commit_id=uuid.UUID(base_commit_id) if base_commit_id else None,
            payload=payload,
        )

    updated_snapshot = await annotation_sync_service.apply_actions(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=sync_in.branch_name,
        current_snapshot=snapshot,
        actions=[action.model_dump(mode="json") for action in sync_in.actions],
        meta=sync_in.meta,
        sync_handler=facade.sync_handler,
        context=context,
    )

    updated_payload = _convert_payload_to_frontend({
        "annotations": updated_snapshot.get("annotations") or [],
        "meta": updated_snapshot.get("meta") or {},
    })
    updated_seq = int(updated_snapshot.get("seq") or 0)
    updated_base = updated_snapshot.get("base_commit_id")

    return AnnotationSyncResponse(
        status="success",
        current_seq_id=updated_seq,
        base_commit_id=uuid.UUID(updated_base) if updated_base else None,
        payload=updated_payload,
    )


@router.get("/lineage/{lineage_id}/annotations", response_model=List[AnnotationRead], dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def get_annotations_by_lineage_id(
        *,
        lineage_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Get all annotations with a specific lineage_id (version chain lookup).
    """
    annotations = await annotation_service.get_by_lineage_id(lineage_id)
    return [AnnotationRead.model_validate(a) for a in annotations]


@router.get("/projects/{project_id}/annotations/count", response_model=int, dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ, ResourceType.PROJECT, "project_id"))
])
async def count_project_annotations(
        *,
        project_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Count annotations for a project.
    """
    return await annotation_service.count_by_project(project_id)


@router.get("/samples/{sample_id}/annotations/count", response_model=int, dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def count_sample_annotations(
        *,
        sample_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Count annotations for a sample.
    """
    return await annotation_service.count_by_sample(sample_id)


# =============================================================================
# Batch Operations - Annotation Save Workflow
# =============================================================================


@router.post("/projects/{project_id}/annotations/save", response_model=dict, dependencies=[
    Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id"))
])
async def save_annotations(
        *,
        project_id: uuid.UUID,
        branch_name: str = "master",
        commit_message: str,
        annotations: list[dict],
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Save annotations and create a new commit.

    This is the core L2 annotation save workflow that:
    1. Creates new Annotation records (with parent_id for modifications)
    2. Creates a new Commit
    3. Creates CAMap entries linking annotations to the commit
    4. Updates the branch HEAD to the new commit

    Args:
        project_id: Project ID
        branch_name: Branch to save to (default: "master")
        commit_message: Commit message describing changes
        annotations: List of annotation data dicts

    Returns:
        Created commit information
    """
    commit = await project_service.save_annotations(
        project_id=project_id,
        branch_name=branch_name,
        annotation_changes=annotations,
        commit_message=commit_message,
        author_id=current_user_id,
    )

    return {
        "commit_id": commit.id,
        "message": commit.message,
        "parent_id": commit.parent_id,
        "stats": commit.stats,
        "created_at": commit.created_at,
    }


# =============================================================================
# Working / Draft Pipeline (Working -> Staging -> Commit)
# =============================================================================


@router.put("/projects/{project_id}/samples/{sample_id}/working", dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def upsert_working_annotations(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        working_in: AnnotationWorkingUpsert,
        working_service: AnnotationWorkingServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    payload = working_in.model_dump(mode="json")
    await working_service.set_working(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=working_in.branch_name,
        payload=payload,
    )


@router.get("/projects/{project_id}/samples/{sample_id}/working", response_model=dict | None, dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def get_working_annotations(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        branch_name: str = "master",
        working_service: AnnotationWorkingServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    payload = await working_service.get_working(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=branch_name,
    )
    return payload


@router.delete("/projects/{project_id}/samples/{sample_id}/working", dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def delete_working_annotations(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        branch_name: str = "master",
        working_service: AnnotationWorkingServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    deleted = await working_service.delete_working(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=branch_name,
    )


@router.put("/projects/{project_id}/samples/{sample_id}/drafts", response_model=AnnotationDraftRead, dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def upsert_annotation_draft(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        draft_in: AnnotationDraftUpsert,
        draft_service: AnnotationDraftServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    draft = await draft_service.upsert_draft(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=draft_in.branch_name,
        payload=draft_in.model_dump(mode="json", exclude={"branch_name"}),
    )
    return AnnotationDraftRead.model_validate(draft)


@router.post("/projects/{project_id}/samples/{sample_id}/drafts/sync", response_model=AnnotationDraftRead | None,
             dependencies=[
                 Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
             ])
async def sync_working_to_draft(
        *,
        project_id: uuid.UUID,
        sample_id: uuid.UUID,
        branch_name: str = "master",
        review_empty: bool = Query(False, description="When true, empty snapshot is promoted as reviewed-empty draft"),
        working_service: AnnotationWorkingServiceDep,
        draft_service: AnnotationDraftServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    snapshot = await working_service.get_snapshot(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=branch_name,
    )
    if not snapshot:
        return None

    annotations = snapshot.get("annotations") or []
    meta = dict(snapshot.get("meta") or {})
    should_promote_empty = len(annotations) == 0 and (review_empty or bool(meta.get("reviewed_empty")))

    if not snapshot.get("dirty") and not should_promote_empty:
        await working_service.delete_working(
            project_id=project_id,
            sample_id=sample_id,
            user_id=current_user_id,
            branch_name=branch_name,
        )
        return None

    if should_promote_empty:
        meta["reviewed_empty"] = True
        meta["reviewed_by"] = str(current_user_id)
        meta["reviewed_at"] = datetime.now(UTC).isoformat()

    payload = {
        "annotations": annotations,
        "meta": meta,
    }

    draft = await draft_service.upsert_draft(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=branch_name,
        payload=payload,
    )
    await working_service.delete_working(
        project_id=project_id,
        sample_id=sample_id,
        user_id=current_user_id,
        branch_name=branch_name,
    )
    return AnnotationDraftRead.model_validate(draft)


@router.get("/projects/{project_id}/drafts", response_model=List[AnnotationDraftRead], dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def list_annotation_drafts(
        *,
        project_id: uuid.UUID,
        branch_name: str | None = None,
        sample_id: uuid.UUID | None = None,
        draft_service: AnnotationDraftServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    drafts = await draft_service.list_drafts(
        project_id=project_id,
        user_id=current_user_id,
        branch_name=branch_name,
        sample_id=sample_id,
    )
    return [AnnotationDraftRead.model_validate(d) for d in drafts]


@router.delete("/projects/{project_id}/drafts", dependencies=[
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id"))
])
async def delete_annotation_drafts(
        *,
        project_id: uuid.UUID,
        branch_name: str | None = None,
        sample_id: uuid.UUID | None = None,
        draft_service: AnnotationDraftServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    deleted = await draft_service.delete_drafts(
        project_id=project_id,
        user_id=current_user_id,
        branch_name=branch_name,
        sample_id=sample_id,
    )


@router.post("/projects/{project_id}/drafts/commit", response_model=dict, dependencies=[
    Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id"))
])
async def commit_annotation_drafts(
        *,
        project_id: uuid.UUID,
        commit_in: AnnotationDraftCommitRequest,
        draft_service: AnnotationDraftServiceDep,
        working_service: AnnotationWorkingServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    commit, used_sample_ids = await draft_service.commit_from_drafts(
        project_id=project_id,
        user_id=current_user_id,
        branch_name=commit_in.branch_name,
        commit_message=commit_in.commit_message,
        sample_ids=commit_in.sample_ids,
    )

    for sample_id in used_sample_ids:
        await working_service.delete_working(
            project_id=project_id,
            sample_id=sample_id,
            user_id=current_user_id,
            branch_name=commit_in.branch_name,
        )

    return {
        "commit_id": commit.id,
        "message": commit.message,
        "parent_id": commit.parent_id,
        "stats": commit.stats,
        "created_at": commit.created_at,
    }
