from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlmodel import Session

from saki_api.core.config import settings
from saki_api.db.session import get_session
from saki_api.models.user import User
from saki_api.models.permission import GlobalRole, Permission
from saki_api.core.permissions import check_permission

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_current_user(
        session: Session = Depends(get_session),
        token: str = Depends(reusable_oauth2)
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = payload.get("sub")
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = session.get(User, token_data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_current_active_admin(
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session)
) -> User:
    """检查用户是否为管理员（ADMIN或SUPER_ADMIN）"""
    if current_user.global_role not in [GlobalRole.ADMIN, GlobalRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges"
        )
    return current_user


def get_current_active_superuser(
        current_user: User = Depends(get_current_user),
) -> User:
    """检查用户是否为超级管理员（向后兼容，但使用新的global_role）"""
    if current_user.global_role != GlobalRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges"
        )
    return current_user
