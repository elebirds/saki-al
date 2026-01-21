"""
API endpoints for User management.

Uses the new RBAC system for permission checking.
"""

import uuid
from typing import Any, List

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.deps import get_current_user, get_session
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
)
from saki_api.models import (
    User,
    Permissions,
)
from saki_api.repositories.user_repository import UserRepository
from saki_api.schemas import (UserCreate, UserRead, UserUpdate, UserListItem)
from saki_api.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def read_user_me(
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get current user.
    """
    repo = UserRepository(session)
    service = UserService(repo)
    return await service.build_user_read(current_user)


@router.get("/list", response_model=List[UserListItem])
async def list_users_simple(
        session: AsyncSession = Depends(get_session),
        skip: int = 0,
        limit: int = 100,
        _current_user: User = Depends(require_permission(Permissions.USER_LIST)),
) -> Any:
    """
    List users with basic info only (for member selection).
    
    Requires user:list permission (not full user:read).
    """
    repo = UserRepository(session)
    service = UserService(repo)
    users = await service.list_active_users(skip=skip, limit=limit)
    return [
        UserListItem(id=u.id, email=u.email, full_name=u.full_name)
        for u in users
    ]


@router.get("/", response_model=List[UserRead])
async def read_users(
        session: AsyncSession = Depends(get_session),
        skip: int = 0,
        limit: int = 100,
        _current_user: User = Depends(require_permission(Permissions.USER_READ)),
) -> Any:
    """
    Retrieve users with full details.
    
    Requires user:read permission (admin level).
    """
    repo = UserRepository(session)
    service = UserService(repo)
    users = await service.list_users(skip=skip, limit=limit)
    return [await service.build_user_read(u) for u in users]


@router.post("/", response_model=UserRead)
async def create_user(
        *,
        session: AsyncSession = Depends(get_session),
        user_in: UserCreate,
        current_user: User = Depends(require_permission(Permissions.USER_CREATE))
) -> Any:
    """
    Create new user.
    """
    repo = UserRepository(session)
    service = UserService(repo)
    user = await service.create_user(user_in, current_user)
    return await service.build_user_read(user)


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
        *,
        session: AsyncSession = Depends(get_session),
        user_id: uuid.UUID,
        user_in: UserUpdate,
        current_user: User = Depends(require_permission(Permissions.USER_UPDATE)),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> Any:
    """
    Update a user.
    """
    repo = UserRepository(session)
    service = UserService(repo)
    user = await service.update_user(user_id, user_in, current_user.id, checker)
    return await service.build_user_read(user)


@router.delete("/{user_id}", response_model=UserRead)
async def delete_user(
        *,
        session: AsyncSession = Depends(get_session),
        user_id: uuid.UUID,
        current_user: User = Depends(require_permission(Permissions.USER_DELETE)),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> Any:
    """
    Delete a user.
    """
    repo = UserRepository(session)
    service = UserService(repo)
    deleted_user = await service.delete_user(user_id, current_user.id, checker)
    return deleted_user