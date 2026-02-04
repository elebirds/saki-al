"""
Annotation Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends

from saki_api.api.service_deps import AnnotationServiceDep, ProjectServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id, require_permission
from saki_api.core.response import ApiResponse
from saki_api.models import Permissions, ResourceType
from saki_api.schemas.annotation import AnnotationCreate, AnnotationHistoryItem, AnnotationRead

router = APIRouter()


# =============================================================================
# Annotation CRUD Endpoints
# =============================================================================


@router.get("/commits/{commit_id}/annotations", response_model=ApiResponse[List[AnnotationRead]], dependencies=[
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
    return ApiResponse(data=[AnnotationRead.model_validate(a) for a in annotations])


@router.get("/samples/{sample_id}/annotations", response_model=ApiResponse[List[AnnotationRead]], dependencies=[
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
    return ApiResponse(data=[AnnotationRead.model_validate(a) for a in annotations])


@router.get("/projects/{project_id}/annotations", response_model=ApiResponse[List[AnnotationRead]], dependencies=[
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
    return ApiResponse(data=[AnnotationRead.model_validate(a) for a in annotations])


@router.get("/annotations/{annotation_id}", response_model=ApiResponse[AnnotationRead], dependencies=[
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
    return ApiResponse(data=AnnotationRead.model_validate(annotation))


@router.get("/annotations/{annotation_id}/history", response_model=ApiResponse[List[AnnotationHistoryItem]],
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
    history = await annotation_service.get_annotation_history(annotation_id, depth)
    return ApiResponse(data=history)


@router.post("/annotations", response_model=ApiResponse[AnnotationRead], dependencies=[
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
    return ApiResponse(data=AnnotationRead.model_validate(annotation))


@router.get("/sync/{sync_id}/annotations", response_model=ApiResponse[List[AnnotationRead]], dependencies=[
    Depends(require_permission(Permissions.ANNOTATION_READ))
])
async def get_annotations_by_sync_id(
        *,
        sync_id: uuid.UUID,
        annotation_service: AnnotationServiceDep,
):
    """
    Get all annotations with a specific sync_id (for cross-view synchronization).
    """
    annotations = await annotation_service.get_by_sync_id(sync_id)
    return ApiResponse(data=[AnnotationRead.model_validate(a) for a in annotations])


@router.get("/projects/{project_id}/annotations/count", response_model=ApiResponse[int], dependencies=[
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
    count = await annotation_service.count_by_project(project_id)
    return ApiResponse(data=count)


@router.get("/samples/{sample_id}/annotations/count", response_model=ApiResponse[int], dependencies=[
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
    count = await annotation_service.count_by_sample(sample_id)
    return ApiResponse(data=count)


# =============================================================================
# Batch Operations - Annotation Save Workflow
# =============================================================================


@router.post("/projects/{project_id}/annotations/save", response_model=ApiResponse[dict], dependencies=[
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

    return ApiResponse(data={
        "commit_id": commit.id,
        "message": commit.message,
        "parent_id": commit.parent_id,
        "stats": commit.stats,
        "created_at": commit.created_at,
    })
