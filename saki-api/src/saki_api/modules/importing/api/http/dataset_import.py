from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from saki_api.app.deps import ImportServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.importing.schema import (
    DatasetImportPrepareRequest,
    ImportExecuteRequest,
    ImportTaskCreateResponse,
)

router = APIRouter()


@router.post(
    "/{dataset_id}/imports/images:execute",
    response_model=ImportTaskCreateResponse,
    dependencies=[
        Depends(require_permission(Permissions.DATASET_IMPORT, ResourceType.DATASET, "dataset_id")),
    ],
)
async def execute_dataset_image_import(
    *,
    dataset_id: uuid.UUID,
    payload: ImportExecuteRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_dataset_images_execute(
        user_id=current_user_id,
        dataset_id=dataset_id,
        request=payload,
    )


@router.post(
    "/{dataset_id}/imports/images:prepare",
    response_model=ImportTaskCreateResponse,
    dependencies=[
        Depends(require_permission(Permissions.DATASET_IMPORT, ResourceType.DATASET, "dataset_id")),
    ],
)
async def prepare_dataset_image_import(
    *,
    dataset_id: uuid.UUID,
    payload: DatasetImportPrepareRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_dataset_images_prepare(
        user_id=current_user_id,
        dataset_id=dataset_id,
        request=payload,
    )
