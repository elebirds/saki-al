"""
Dataset Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends

from saki_api.api.service_deps import DatasetServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id, require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate

router = APIRouter()


@router.post("/", response_model=DatasetRead, dependencies=[
    Depends(require_permission(Permissions.DATASET_CREATE_ALL))
])
async def create_dataset(
        *,
        dataset_in: DatasetCreate,
        dataset_service: DatasetServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> DatasetRead:
    """
    Create a new dataset.
    """
    return DatasetRead.model_validate(await dataset_service.create_dataset(dataset_in, current_user_id))


@router.get("/", response_model=List[DatasetRead])
async def list_datasets(
        *,
        dataset_service: DatasetServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> List[DatasetRead]:
    """
    List datasets available to the user (owned).
    """
    # Simply mapping to get_by_owner for now.
    # TODO: In future, this might include shared datasets.
    return [DatasetRead.model_validate(i) for i in await dataset_service.repository.get_by_owner(current_user_id)]


@router.get("/{dataset_id}", response_model=DatasetRead, dependencies=[
    Depends(require_permission(Permissions.DATASET_READ, ResourceType.DATASET, "dataset_id"))
])
async def get_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep
) -> DatasetRead:
    """
    Get a dataset by ID.
    """
    return DatasetRead.model_validate(await dataset_service.get_by_id_or_raise(dataset_id))


@router.put("/{dataset_id}", response_model=DatasetRead, dependencies=[
    Depends(require_permission(Permissions.DATASET_UPDATE, ResourceType.DATASET, "dataset_id"))
])
async def update_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_in: DatasetUpdate,
        dataset_service: DatasetServiceDep
) -> DatasetRead:
    """
    Update a dataset.
    """
    await dataset_service.get_by_id_or_raise(dataset_id)
    updated = await dataset_service.repository.update(dataset_id, dataset_in.model_dump(exclude_unset=True))
    return DatasetRead.model_validate(updated)


@router.delete("/{dataset_id}", dependencies=[
    Depends(require_permission(Permissions.DATASET_DELETE, ResourceType.DATASET, "dataset_id"))
])
async def delete_dataset(
        *,
        dataset_id: uuid.UUID,
        dataset_service: DatasetServiceDep
) -> dict:
    """
    Delete a dataset and all its samples.
    """
    dataset = await dataset_service.get_by_id_or_raise(dataset_id)
    await dataset_service.repository.delete(dataset)
    return {"ok": True, "message": "Dataset deleted successfully"}
