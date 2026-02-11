"""
API endpoints for User management.

Uses the new RBAC system for permission checking.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile, File

from saki_api.api.service_deps import UserServiceDep
from saki_api.core.rbac import (
    require_permission,
)
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.models import (
    Permissions,
)
from saki_api.repositories.query import Pagination
from saki_api.schemas import (UserCreate, UserRead, UserUpdate, UserListItem)
from saki_api.schemas.pagination import PaginationResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    description="Get current user"
)
async def read_user_me(
        service: UserServiceDep,
        user_id: uuid.UUID = Depends(get_current_user_id)
) -> UserRead:
    """
    Get current user.
    """
    return await service.get_profile_by_id(user_id)


@router.post(
    "/me/avatar",
    response_model=UserRead,
    summary="Upload current user avatar",
    description="Upload and update current user avatar image."
)
async def upload_user_avatar(
        service: UserServiceDep,
        file: UploadFile = File(..., description="Avatar image (PNG/JPEG/WebP)"),
        user_id: uuid.UUID = Depends(get_current_user_id),
) -> UserRead:
    return await service.upload_current_user_avatar(user_id=user_id, file=file)


@router.get(
    "/list",
    response_model=PaginationResponse[UserListItem],
    dependencies=[Depends(require_permission(Permissions.USER_LIST))],
    summary="List users for selection",
    description="List users with basic info only (for member selection). Requires user:list permission."
)
async def list_users_simple(
        service: UserServiceDep,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
        q: str | None = Query(default=None, description="Fuzzy search by email/full name"),
) -> PaginationResponse[UserListItem]:
    """
    List users with basic info only (for member selection).
    
    Requires user:list permission (not full user:read).
    """
    users = await service.list_active_paginated(Pagination.from_page(page=page, limit=limit), q=q)
    return users.map(UserListItem.model_validate)


@router.get(
    "",
    response_model=PaginationResponse[UserRead],
    dependencies=[Depends(require_permission(Permissions.USER_READ))],
    summary="List users with full details",
    description="Retrieve users with full details. Requires user:read permission (admin level)."
)
async def read_users(
        service: UserServiceDep,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
) -> PaginationResponse[UserRead]:
    """
    Retrieve users with full details.
    
    Requires user:read permission (admin level).
    """
    return await service.list_with_roles_paginated(Pagination.from_page(page=page, limit=limit))


@router.post(
    "",
    response_model=UserRead,
    dependencies=[Depends(require_permission(Permissions.USER_CREATE))],
    summary="Create new user",
    description="Create new user"
)
async def create_user(
        *,
        user_in: UserCreate,
        service: UserServiceDep,
) -> Any:
    """
    Create new user.
    """
    user = await service.create(user_in)
    return await service.get_profile_by_id(user.id)


@router.put(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_permission(Permissions.USER_UPDATE))],
    summary="Update a user",
    description="Update a user"
)
async def update_user(
        *,
        user_id: uuid.UUID,
        user_in: UserUpdate,
        service: UserServiceDep,
) -> Any:
    """
    Update a user.
    """
    user = await service.update_user(user_id, user_in)
    return await service.get_profile_by_id(user.id)


@router.delete(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_permission(Permissions.USER_DELETE))],
    summary="Delete a user",
    description="Delete a user"
)
async def delete_user(
        *,
        user_id: uuid.UUID,
        service: UserServiceDep
) -> Any:
    """
    Delete a user.
    """
    return await service.delete_user(user_id)
