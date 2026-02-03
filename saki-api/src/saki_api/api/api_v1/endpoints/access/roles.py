"""
API endpoints for Role management.

Provides CRUD operations for roles and user role assignments.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from saki_api.api.service_deps import RoleServiceDep, UserRoleServiceDep
from saki_api.core.exceptions import NotFoundAppException
from saki_api.core.rbac import (
    require_permission,
)
from saki_api.models import RoleType, Permissions
from saki_api.repositories.query import Pagination
from saki_api.schemas import (
    RoleCreate, RoleRead, RoleUpdate,
    UserSystemRoleAssign, UserSystemRoleRead,
)

router = APIRouter()


# ============================================================================
# Role CRUD
# ============================================================================

@router.get(
    "",
    response_model=List[RoleRead],
    dependencies=[Depends(require_permission(Permissions.ROLE_READ))],
    summary="List all roles",
    description="List all roles. Optionally filter by type (system or resource)."
)
async def list_roles(
        service: RoleServiceDep,
        type: Optional[RoleType] = Query(None, description="Filter by role type"),
        offset: int = 0,
        limit: int = 100,
):
    """
    List all roles.
    
    Optionally filter by type (system or resource).
    """
    roles = await service.list_by_type(
        role_type=type,
        pagination=Pagination(offset=offset, limit=limit)
    )
    return [await service.build_role_read(role) for role in roles]


@router.get(
    "/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission(Permissions.ROLE_READ))],
    summary="Get a role by ID",
    description="Get a role by ID"
)
async def get_role(
        role_id: uuid.UUID,
        service: RoleServiceDep,
):
    """Get a role by ID."""
    role = await service.get_by_id(role_id)
    if role is None:
        raise NotFoundAppException("Role not found")
    return await service.build_role_read(role)


@router.post(
    "",
    response_model=RoleRead,
    dependencies=[Depends(require_permission(Permissions.ROLE_CREATE))],
    summary="Create a custom role",
    description="Create a custom role. System preset roles cannot be created through this endpoint."
)
async def create_role(
        role_in: RoleCreate,
        service: RoleServiceDep
):
    """
    Create a custom role.
    
    System preset roles cannot be created through this endpoint.
    """
    role = await service.create(role_in)
    return await service.build_role_read(role)


@router.put(
    "/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission(Permissions.ROLE_UPDATE))],
    summary="Update a role",
    description="Update a role. System preset roles have limited update capabilities."
)
async def update_role(
        role_id: uuid.UUID,
        role_in: RoleUpdate,
        service: RoleServiceDep
):
    """
    Update a role.
    
    System preset roles have limited update capabilities.
    """
    role = await service.update(role_id, role_in)
    return await service.build_role_read(role)


@router.delete(
    "/{role_id}",
    dependencies=[Depends(require_permission(Permissions.ROLE_DELETE))],
    summary="Delete a role",
    description="Delete a role. System preset roles cannot be deleted. Roles that are in use cannot be deleted."
)
async def delete_role(
        role_id: uuid.UUID,
        service: RoleServiceDep
):
    """
    Delete a role.
    
    System preset roles cannot be deleted.
    Roles that are in use cannot be deleted.
    """
    await service.delete(role_id)


# ============================================================================
# User Role Management
# ============================================================================

@router.get(
    "/users/{user_id}/roles",
    response_model=List[UserSystemRoleRead],
    dependencies=[Depends(require_permission(Permissions.USER_ROLE_READ))],
    summary="Get user's system roles",
    description="Get all system roles assigned to a user"
)
async def get_user_roles(
        user_id: uuid.UUID,
        user_role_service: UserRoleServiceDep,
):
    """Get all system roles assigned to a user."""
    return await user_role_service.get_user_roles_read(user_id)


@router.post(
    "/users/{user_id}/roles",
    response_model=UserSystemRoleRead,
    dependencies=[Depends(require_permission(Permissions.ROLE_ASSIGN))],
    summary="Assign a system role to a user",
    description="Assign a system role to a user. The user_id is provided in the URL path."
)
async def assign_user_role(
        user_id: uuid.UUID,
        role_in: UserSystemRoleAssign,
        user_role_service: UserRoleServiceDep,
):
    """Assign a system role to a user."""
    return await user_role_service.assign_user_system_role(
        user_id=user_id,
        role_in=role_in,
    )


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    dependencies=[Depends(require_permission(Permissions.ROLE_REVOKE))],
    summary="Revoke a system role from a user",
    description="Revoke a system role from a user"
)
async def revoke_user_role(
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        user_role_service: UserRoleServiceDep,
):
    """Revoke a system role from a user."""
    return await user_role_service.revoke_user_system_role(
        user_id=user_id,
        role_id=role_id,
    )
