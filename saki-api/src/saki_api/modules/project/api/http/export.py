from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from saki_api.app.deps import ExportServiceDep
from saki_api.modules.access.api.dependencies import require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.project.api.export import (
    ProjectExportChunkRequest,
    ProjectExportChunkResponse,
    ProjectExportResolveRequest,
    ProjectExportResolveResponse,
    ProjectIOCapabilitiesRead,
)

router = APIRouter()


@router.get(
    "/{project_id}/io-capabilities",
    response_model=ProjectIOCapabilitiesRead,
    dependencies=[
        Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id"))
    ],
)
async def get_project_io_capabilities(
    *,
    project_id: uuid.UUID,
    export_service: ExportServiceDep,
) -> ProjectIOCapabilitiesRead:
    return await export_service.get_io_capabilities(project_id=project_id)


@router.post(
    "/{project_id}/exports/resolve",
    response_model=ProjectExportResolveResponse,
    dependencies=[
        Depends(require_permission(Permissions.PROJECT_EXPORT, ResourceType.PROJECT, "project_id"))
    ],
)
async def resolve_project_export(
    *,
    project_id: uuid.UUID,
    payload: ProjectExportResolveRequest,
    export_service: ExportServiceDep,
) -> ProjectExportResolveResponse:
    return await export_service.resolve_export(project_id=project_id, payload=payload)


@router.post(
    "/{project_id}/exports/chunk",
    response_model=ProjectExportChunkResponse,
    dependencies=[
        Depends(require_permission(Permissions.PROJECT_EXPORT, ResourceType.PROJECT, "project_id"))
    ],
)
async def get_project_export_chunk(
    *,
    project_id: uuid.UUID,
    payload: ProjectExportChunkRequest,
    export_service: ExportServiceDep,
) -> ProjectExportChunkResponse:
    return await export_service.get_export_chunk(project_id=project_id, payload=payload)
