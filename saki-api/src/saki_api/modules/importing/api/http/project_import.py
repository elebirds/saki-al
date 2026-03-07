from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from saki_api.app.deps import ImportServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.importing.schema import (
    ImportExecuteRequest,
    ProjectAnnotationImportPrepareRequest,
    ProjectAssociatedImportPrepareRequest,
    ImportTaskCreateResponse,
)

router = APIRouter()


_PROJECT_IMPORT_PERMISSIONS = [
    Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id")),
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id")),
]


@router.post(
    "/{project_id}/imports/annotations:execute",
    response_model=ImportTaskCreateResponse,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def execute_project_annotation_import(
    *,
    project_id: uuid.UUID,
    payload: ImportExecuteRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_project_annotations_execute(
        user_id=current_user_id,
        project_id=project_id,
        request=payload,
    )


@router.post(
    "/{project_id}/imports/annotations:prepare",
    response_model=ImportTaskCreateResponse,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def prepare_project_annotation_import(
    *,
    project_id: uuid.UUID,
    payload: ProjectAnnotationImportPrepareRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_project_annotations_prepare(
        user_id=current_user_id,
        project_id=project_id,
        request=payload,
    )


@router.post(
    "/{project_id}/imports/associated:execute",
    response_model=ImportTaskCreateResponse,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def execute_project_associated_import(
    *,
    project_id: uuid.UUID,
    payload: ImportExecuteRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_project_associated_execute(
        user_id=current_user_id,
        project_id=project_id,
        request=payload,
    )


@router.post(
    "/{project_id}/imports/associated:prepare",
    response_model=ImportTaskCreateResponse,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def prepare_project_associated_import(
    *,
    project_id: uuid.UUID,
    payload: ProjectAssociatedImportPrepareRequest,
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    return await service.start_project_associated_prepare(
        user_id=current_user_id,
        project_id=project_id,
        request=payload,
    )
