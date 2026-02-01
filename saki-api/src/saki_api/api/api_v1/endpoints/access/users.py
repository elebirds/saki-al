"""
API endpoints for User management.

Uses the new RBAC system for permission checking.
"""

import uuid
from typing import Any, List

from fastapi import APIRouter, Depends

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


@router.get(
    "/list",
    response_model=List[UserListItem],
    dependencies=[Depends(require_permission(Permissions.USER_LIST))],
    summary="List users for selection",
    description="List users with basic info only (for member selection). Requires user:list permission."
)
async def list_users_simple(
        service: UserServiceDep,
        skip: int = 0,
        limit: int = 100,
) -> List[UserListItem]:
    """
    List users with basic info only (for member selection).
    
    Requires user:list permission (not full user:read).
    """
    users = await service.list_active(Pagination(skip=skip, limit=limit))
    return [UserListItem.model_validate(u) for u in users]


@router.get(
    "/",
    response_model=List[UserRead],
    dependencies=[Depends(require_permission(Permissions.USER_READ))],
    summary="List users with full details",
    description="Retrieve users with full details. Requires user:read permission (admin level)."
)
async def read_users(
        service: UserServiceDep,
        skip: int = 0,
        limit: int = 100,
) -> List[UserRead]:
    """
    Retrieve users with full details.
    
    Requires user:read permission (admin level).
    """
    return await service.list_with_roles(Pagination(skip=skip, limit=limit))


@router.post(
    "/",
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
