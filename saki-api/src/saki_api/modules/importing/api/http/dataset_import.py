from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from saki_api.app.deps import ImportServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.importing.schema import (
    ImportDryRunResponse,
    ImportExecuteRequest,
    ImportTaskCreateResponse,
    NameCollisionPolicy,
    PathFlattenMode,
)

router = APIRouter()


@router.post(
    "/{dataset_id}/imports/images:dry-run",
    response_model=ImportDryRunResponse,
    dependencies=[
        Depends(require_permission(Permissions.DATASET_IMPORT, ResourceType.DATASET, "dataset_id")),
    ],
)
async def dry_run_dataset_image_import(
    *,
    dataset_id: uuid.UUID,
    file: UploadFile = File(..., description="ZIP file"),
    path_flatten_mode: PathFlattenMode = Form(PathFlattenMode.BASENAME),
    name_collision_policy: NameCollisionPolicy = Form(NameCollisionPolicy.ABORT),
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportDryRunResponse:
    return await service.dry_run_dataset_images(
        user_id=current_user_id,
        dataset_id=dataset_id,
        zip_file=file,
        path_flatten_mode=path_flatten_mode,
        name_collision_policy=name_collision_policy,
    )


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
