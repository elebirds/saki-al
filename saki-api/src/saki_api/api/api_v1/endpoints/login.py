"""
Authentication and Authorization endpoints.

Provides login, registration, password management, and permission info.
"""

import uuid
from datetime import timedelta
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, Query
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api import deps
from saki_api.core import security, settings
from saki_api.core.rbac import (
    PermissionChecker,
    get_permission_checker,
)
from saki_api.db.session import get_session
from saki_api.models import User
from saki_api.repositories.user_repository import UserRepository
from saki_api.schemas import UserRead, UserCreate
from saki_api.services.user_service import UserService
from saki_api.services.auth_service import AuthService
from saki_api.services.permission_query_service import PermissionQueryService

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RoleInfo(BaseModel):
    """Basic role information."""
    id: uuid.UUID
    name: str
    displayName: str


class PermissionInfo(BaseModel):
    """Permission with scope."""
    permission: str
    scope: str


class UserPermissionsResponse(BaseModel):
    """Response for user permissions endpoint."""
    userId: uuid.UUID
    systemRoles: List[RoleInfo]
    resourceRole: Optional[RoleInfo] = None
    permissions: List[str]
    isSuperAdmin: bool
    isOwner: Optional[bool] = None


@router.post("/login/access-token")
async def login_access_token(
        session: AsyncSession = Depends(get_session),
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    repo = UserRepository(session)
    auth = AuthService(repo)
    return await auth.login_access_token(form_data)


@router.post("/register", response_model=UserRead)
async def register_user(
        user_in: UserCreate,
        session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Create new user without the need to be logged in.
    
    New users are automatically assigned the default system role.
    """
    repo = UserRepository(session)
    service = UserService(repo)
    user = await service.create_user(user_in, None)  # No current_user for registration
    return await service.build_user_read(user)


@router.post("/login/refresh-token")
def refresh_token(
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Refresh access token.
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            current_user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }


@router.post("/change-password")
async def change_password(
        password_data: ChangePasswordRequest,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Change user password.
    """
    repo = UserRepository(session)
    auth = AuthService(repo)
    return await auth.change_password(
        current_user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )


@router.get("/permissions", response_model=UserPermissionsResponse)
async def get_my_permissions(
        resource_type: Optional[str] = Query(None, description="Resource type (e.g., 'dataset')"),
        resource_id: Optional[uuid.UUID] = Query(None, description="Resource ID"),
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> UserPermissionsResponse:
    """
    Get current user's permissions.
    
    If resource_type and resource_id are provided, includes resource-specific
    permissions and role information.
    
    This endpoint is used by the frontend to determine what UI elements to show.
    """
    svc = PermissionQueryService(session)
    payload = await svc.get_my_permissions(
        current_user=current_user,
        checker=checker,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return UserPermissionsResponse(**payload)
