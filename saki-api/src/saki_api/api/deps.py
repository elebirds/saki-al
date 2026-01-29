from fastapi import Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.rbac.dependencies import get_current_user, get_current_user_id
from saki_api.db.session import get_session
from saki_api.models.user import User


async def get_current_active_superuser(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
) -> User:
    """检查用户是否为超级管理员"""
    # Import here to avoid circular import
    from saki_api.core.rbac.checker import PermissionChecker

    checker = PermissionChecker(session)
    if not checker.is_super_admin(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges"
        )
    return current_user
