"""
Label Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends

from saki_api.app.deps import LabelServiceDep
from saki_api.modules.access.api.dependencies import require_permission
from saki_api.modules.project.api.label import LabelCreate, LabelRead, LabelUpdate
from saki_api.modules.access.domain.rbac import Permissions, ResourceType

router = APIRouter()


# =============================================================================
# Label CRUD Endpoints
# =============================================================================


@router.post("/projects/{project_id}/labels", response_model=LabelRead, dependencies=[
    Depends(require_permission(Permissions.LABEL_MANAGE, ResourceType.PROJECT, "project_id"))
])
async def create_label(
        *,
        project_id: uuid.UUID,
        label_in: LabelCreate,
        label_service: LabelServiceDep,
):
    """
    Create a new label in a project.

    Auto-assigns sort_order if not provided (appends to end).
    """
    # Ensure label belongs to the project in the URL
    label_in.project_id = project_id
    label = await label_service.create_label(label_in)
    return LabelRead.model_validate(label)


@router.get("/projects/{project_id}/labels", response_model=List[LabelRead], dependencies=[
    Depends(require_permission(Permissions.LABEL_READ, ResourceType.PROJECT, "project_id"))
])
async def list_labels(
        *,
        project_id: uuid.UUID,
        label_service: LabelServiceDep,
):
    """
    Get all labels for a project, ordered by sort_order.
    """
    labels = await label_service.get_by_project(project_id)
    return [LabelRead.model_validate(l) for l in labels]


@router.get("/labels/{label_id}", response_model=LabelRead, dependencies=[
    Depends(require_permission(Permissions.LABEL_READ))
])
async def get_label(
        *,
        label_id: uuid.UUID,
        label_service: LabelServiceDep,
):
    """
    Get a label by ID.
    """
    label = await label_service.get_by_id_or_raise(label_id)
    return LabelRead.model_validate(label)


@router.put("/labels/{label_id}", response_model=LabelRead, dependencies=[
    Depends(require_permission(Permissions.LABEL_MANAGE))
])
async def update_label(
        *,
        label_id: uuid.UUID,
        label_in: LabelUpdate,
        label_service: LabelServiceDep,
):
    """
    Update a label.

    Prevents name conflicts within the same project.
    """
    label = await label_service.update_label(label_id, label_in)
    return LabelRead.model_validate(label)


@router.delete("/labels/{label_id}", response_model=None, dependencies=[
    Depends(require_permission(Permissions.LABEL_MANAGE))
])
async def delete_label(
        *,
        label_id: uuid.UUID,
        label_service: LabelServiceDep,
):
    """
    Delete a label.

    Warning: This may affect annotations that reference this label.
    """
    await label_service.get_by_id_or_raise(label_id)
    await label_service.repository.delete(label_id)


# =============================================================================
# Batch Operations
# =============================================================================


@router.post("/projects/{project_id}/labels/batch", response_model=List[LabelRead], dependencies=[
    Depends(require_permission(Permissions.LABEL_MANAGE, ResourceType.PROJECT, "project_id"))
])
async def batch_create_labels(
        *,
        project_id: uuid.UUID,
        labels: List[dict],
        label_service: LabelServiceDep,
):
    """
    Batch create labels in a project.

    Request body should be a list of label objects with at least 'name' field.
    Example: [{"name": "Object", "color": "#ff0000"}, {"name": "Background"}]

    Auto-assigns sort_order if not provided.
    """
    created = await label_service.batch_create(project_id, labels)
    return [LabelRead.model_validate(l) for l in created]


@router.post("/projects/{project_id}/labels/reorder", response_model=List[LabelRead], dependencies=[
    Depends(require_permission(Permissions.LABEL_MANAGE, ResourceType.PROJECT, "project_id"))
])
async def reorder_labels(
        *,
        project_id: uuid.UUID,
        label_ids: List[uuid.UUID],
        label_service: LabelServiceDep,
):
    """
    Reorder labels in a project.

    Request body should be a list of label IDs in the desired order.
    Example: ["uuid1", "uuid3", "uuid2"]
    """
    reordered = await label_service.reorder(project_id, label_ids)
    return [LabelRead.model_validate(l) for l in reordered]
