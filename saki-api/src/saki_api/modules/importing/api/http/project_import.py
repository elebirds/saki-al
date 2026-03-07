from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from saki_api.app.deps import ImportServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.importing.schema import (
    AssociatedDatasetMode,
    ImportDryRunResponse,
    ImportExecuteRequest,
    ImportFormat,
    ProjectAnnotationImportPrepareRequest,
    ProjectAssociatedImportPrepareRequest,
    ImportTaskCreateResponse,
    NameCollisionPolicy,
    PathFlattenMode,
)

router = APIRouter()


_PROJECT_IMPORT_PERMISSIONS = [
    Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id")),
    Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id")),
]


@router.post(
    "/{project_id}/imports/annotations:dry-run",
    response_model=ImportDryRunResponse,
    deprecated=True,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def dry_run_project_annotation_import(
    *,
    project_id: uuid.UUID,
    file: UploadFile = File(..., description="ZIP file"),
    format_profile: ImportFormat = Form(...),
    dataset_id: uuid.UUID = Form(...),
    branch_name: str = Form("master"),
    path_flatten_mode: PathFlattenMode = Form(PathFlattenMode.BASENAME),
    name_collision_policy: NameCollisionPolicy = Form(NameCollisionPolicy.ABORT),
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportDryRunResponse:
    return await service.dry_run_project_annotations(
        user_id=current_user_id,
        project_id=project_id,
        dataset_id=dataset_id,
        branch_name=branch_name,
        fmt=format_profile,
        zip_file=file,
        path_flatten_mode=path_flatten_mode,
        name_collision_policy=name_collision_policy,
    )


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
    "/{project_id}/imports/associated:dry-run",
    response_model=ImportDryRunResponse,
    deprecated=True,
    dependencies=_PROJECT_IMPORT_PERMISSIONS,
)
async def dry_run_project_associated_import(
    *,
    project_id: uuid.UUID,
    file: UploadFile = File(..., description="ZIP file"),
    format_profile: ImportFormat = Form(...),
    branch_name: str = Form("master"),
    path_flatten_mode: PathFlattenMode = Form(PathFlattenMode.BASENAME),
    name_collision_policy: NameCollisionPolicy = Form(NameCollisionPolicy.ABORT),
    target_dataset_mode: AssociatedDatasetMode = Form(...),
    target_dataset_id: uuid.UUID | None = Form(default=None),
    new_dataset_name: str | None = Form(default=None),
    new_dataset_description: str | None = Form(default=None),
    service: ImportServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportDryRunResponse:
    return await service.dry_run_project_associated(
        user_id=current_user_id,
        project_id=project_id,
        branch_name=branch_name,
        fmt=format_profile,
        path_flatten_mode=path_flatten_mode,
        name_collision_policy=name_collision_policy,
        target_mode=target_dataset_mode,
        target_dataset_id=target_dataset_id,
        new_dataset_name=new_dataset_name,
        new_dataset_description=new_dataset_description,
        zip_file=file,
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
