"""
Permission Query endpoints.

Provides separated endpoints for system and resource permissions.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from saki_api.app.deps import PermissionQueryServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.api.permission import (
    SystemPermissionsResponse,
    ResourcePermissionsResponse,
)

router = APIRouter()


@router.get(
    "/system",
    response_model=SystemPermissionsResponse,
    summary="Get system permissions",
    description="Get system-level permissions for the current user. Returns only permissions from system roles."
)
async def get_system_permissions(
        service: PermissionQueryServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> SystemPermissionsResponse:
    return await service.get_system_permissions(current_user_id)


@router.get(
    "/resource",
    response_model=ResourcePermissionsResponse,
    summary="Get resource permissions",
    description="Get resource-specific permissions for the current user. Returns only permissions from resource roles."
)
async def get_resource_permissions(
        service: PermissionQueryServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        resource_type: str = Query(..., description="Resource type (e.g., 'dataset')"),
        resource_id: uuid.UUID = Query(..., description="Resource ID"),
) -> ResourcePermissionsResponse:
    return await service.get_resource_permissions(
        current_user_id,
        resource_type,
        resource_id,
    )
