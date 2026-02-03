"""
Authentication and Authorization endpoints.

Provides login, registration, password management, and permission info.
"""
import uuid

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from saki_api.api.service_deps import AuthServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.schemas import UserRead, UserCreate
from saki_api.schemas.auth import LoginResponse

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RefreshTokenRequest(BaseModel):
    token: str


@router.post("/login/access-token", response_model=LoginResponse)
async def login_access_token(
        service: AuthServiceDep,
        form_data: OAuth2PasswordRequestForm = Depends()
) -> LoginResponse:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    return await service.login(form_data)


@router.post("/login/refresh-token", response_model=LoginResponse)
async def refresh_token(
        request: RefreshTokenRequest,
        service: AuthServiceDep,
) -> LoginResponse:
    """
    Refresh access token using a refresh token.

    This endpoint accepts a refresh token (not an access token) and returns
    a new access token. The refresh token should be obtained during login.
    """
    return await service.refresh_access_token(request.token)


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


@router.post("/change-password")
async def change_password(
        password_data: ChangePasswordRequest,
        service: AuthServiceDep,
        user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Change user password.
    
    Requires authentication. The user can only change their own password.
    """
    await service.change_password(
        user_id=user_id,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )
