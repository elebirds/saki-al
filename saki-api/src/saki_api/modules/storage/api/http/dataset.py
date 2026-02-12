"""
Dataset Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from saki_api.app.deps import DatasetServiceDep
from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.api.resource_member import ResourceMemberCreateRequest, ResourceMemberRead, \
    ResourceMemberUpdateRequest
from saki_api.modules.access.api.role import RoleReadMinimal
from saki_api.modules.shared.modeling import Permissions, ResourceType, Dataset
from saki_api.modules.storage.api.dataset import DatasetCreate, DatasetRead, DatasetUpdate

router = APIRouter()


@router.post("", dependencies=[
    Depends(require_permission(Permissions.DATASET_CREATE_ALL))
])
async def create_dataset(
        *,
        dataset_in: DatasetCreate,
        dataset_service: DatasetServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Create a new dataset.
    """
    await dataset_service.create_dataset(dataset_in, current_user_id)


@router.get("", response_model=PaginationResponse[DatasetRead])
async def list_datasets(
        *,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        dataset_service: DatasetServiceDep,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
        q: str | None = Query(default=None),
) -> PaginationResponse[DatasetRead]:
    """
    List datasets available to the current user.
    """
    pagination = Pagination.from_page(page=page, limit=limit)
    datasets = await dataset_service.list_datasets(current_user_id, pagination, q=q)
    return datasets.map(DatasetRead.model_validate)


@router.get("/{dataset_id}", response_model=DatasetRead, dependencies=[
    Depends(require_permission(Permissions.DATASET_READ, ResourceType.DATASET, "dataset_id"))
])
async def get_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep
) -> Dataset:
    """
    Get a dataset by ID.
    """
    return await dataset_service.get_by_id_or_raise(dataset_id)


@router.put("/{dataset_id}", response_model=Dataset, dependencies=[
    Depends(require_permission(Permissions.DATASET_UPDATE, ResourceType.DATASET, "dataset_id"))
])
async def update_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_in: DatasetUpdate,
        dataset_service: DatasetServiceDep
) -> Dataset:
    """
    Update a dataset.
    """
    await dataset_service.get_by_id_or_raise(dataset_id)
    return await dataset_service.repository.update(dataset_id, dataset_in.model_dump(exclude_unset=True))


@router.delete("/{dataset_id}", dependencies=[
    Depends(require_permission(Permissions.DATASET_DELETE, ResourceType.DATASET, "dataset_id"))
])
async def delete_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep
):
    """
    Delete a dataset and all its samples.
    """
    await dataset_service.get_by_id_or_raise(dataset_id)
    await dataset_service.repository.delete(dataset_id)


# =============================================================================
# Dataset Member Management Endpoints
# =============================================================================


@router.get("/{dataset_id}/members", response_model=List[ResourceMemberRead], dependencies=[
    Depends(require_permission(Permissions.DATASET_ASSIGN, ResourceType.DATASET, "dataset_id"))
])
async def get_dataset_members(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep,
) -> List[ResourceMemberRead]:
    """
    Get all members of a dataset with user and role information.
    """
    return await dataset_service.get_dataset_members(dataset_id)


@router.post("/{dataset_id}/members", dependencies=[
    Depends(require_permission(Permissions.DATASET_ASSIGN, ResourceType.DATASET, "dataset_id"))
])
async def add_dataset_member(
        *,
        dataset_id: uuid.UUID,
        member: ResourceMemberCreateRequest,
        dataset_service: DatasetServiceDep,
) -> None:
    """
    Add a member to a dataset.
    
    Cannot assign owner role - owner is determined by dataset creator.
    """
    await dataset_service.add_dataset_member(dataset_id, member)


@router.put("/{dataset_id}/members/{user_id}", dependencies=[
    Depends(require_permission(Permissions.DATASET_ASSIGN, ResourceType.DATASET, "dataset_id"))
])
async def update_dataset_member(
        *,
        dataset_id: uuid.UUID,
        user_id: uuid.UUID,
        member: ResourceMemberUpdateRequest,
        dataset_service: DatasetServiceDep,
) -> None:
    """
    Update a dataset member's role.
    
    Cannot update the dataset owner's membership or assign owner role.
    """
    await dataset_service.update_dataset_member(dataset_id, user_id, member)


@router.delete("/{dataset_id}/members/{user_id}", dependencies=[
    Depends(require_permission(Permissions.DATASET_ASSIGN, ResourceType.DATASET, "dataset_id"))
])
async def remove_dataset_member(
        *,
        dataset_id: uuid.UUID,
        user_id: uuid.UUID,
        dataset_service: DatasetServiceDep,
) -> None:
    """
    Remove a member from a dataset.

    Cannot remove the dataset owner.
    """
    await dataset_service.remove_dataset_member(dataset_id, user_id)


@router.get("/{dataset_id}/available-roles", response_model=List[RoleReadMinimal], dependencies=[
    Depends(require_permission(Permissions.DATASET_READ, ResourceType.DATASET, "dataset_id"))
])
async def get_available_dataset_roles(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep,
) -> List[RoleReadMinimal]:
    """
    Get available roles for dataset members.
    """
    roles = await dataset_service.get_available_dataset_roles(dataset_id)
    return [RoleReadMinimal.model_validate(role) for role in roles]
