from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from saki_api.api import deps
from saki_api.core import security
from saki_api.core.config import settings
from saki_api.db.session import get_session
from saki_api.models.user import User, UserCreate, UserRead
from sqlmodel import Session, select

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login/access-token")
def login_access_token(
        session: Session = Depends(get_session),
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    statement = select(User).where(User.email == form_data.username)
    user = session.exec(statement).first()

    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    response = {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

    # 如果用户需要更改密码，在响应中添加标志
    if user.must_change_password:
        response["must_change_password"] = True

    return response


@router.post("/register", response_model=UserRead)
def register_user(
        user_in: UserCreate,
        session: Session = Depends(get_session),
) -> Any:
    """
    Create new user without the need to be logged in
    """
    statement = select(User).where(User.email == user_in.email)
    user = session.exec(statement).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system",
        )

    user_data = user_in.model_dump(exclude={"password"})
    user_data["hashed_password"] = security.get_password_hash(user_in.password)
    user = User.model_validate(user_data)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login/refresh-token")
def refresh_token(
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Refresh access token
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            current_user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }


@router.post("/change-password")
def change_password(
        password_data: ChangePasswordRequest,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Change user password
    """
    # 验证旧密码
    if not security.verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")

    # 验证新密码格式（必须是前端哈希后的）
    if not security.is_frontend_hashed_password(password_data.new_password):
        raise HTTPException(
            status_code=400,
            detail="New password must be in the correct format (frontend hashed)"
        )

    # 更新密码
    current_user.hashed_password = security.get_password_hash(password_data.new_password)
    # 清除必须更改密码的标志
    current_user.must_change_password = False

    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    return {"message": "Password changed successfully"}
