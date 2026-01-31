"""
Authentication and Authorization endpoints.

Provides login, registration, password management, and permission info.
"""

import uuid
from typing import Any, Optional, List

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from saki_api.api import deps
from saki_api.api.service_deps import AuthServiceDep
from saki_api.models import User
from saki_api.schemas import UserRead, UserCreate

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str

class PermissionInfo(BaseModel):
    """Permission with scope."""
    permission: str
    scope: str

@router.post("/login/access-token")
async def login_access_token(
        service: AuthServiceDep,
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    return await service.login(form_data)


@router.post("/register", response_model=UserRead)
async def register_user(
        user_in: UserCreate,
        service: AuthServiceDep
) -> UserRead:
    """
    Create new user without the need to be logged in.
    
    New users are automatically assigned the default system role.
    """
    return await service.register(user_in)


@router.post("/login/refresh-token")
async def refresh_token(
        token_data: RefreshTokenRequest,
        service: AuthServiceDep,
) -> Any:
    """
    Refresh access token using a refresh token.
    
    This endpoint accepts a refresh token (not an access token) and returns
    a new access token. The refresh token should be obtained during login.
    """
    return await service.refresh_access_token(token_data.refresh_token)


@router.post("/change-password")
async def change_password(
        password_data: ChangePasswordRequest,
        service: AuthServiceDep,
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Change user password.
    
    Requires authentication. The user can only change their own password.
    """
    return await service.change_password(
        user_id=current_user.id,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )
