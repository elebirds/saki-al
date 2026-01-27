from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.context import get_current_user_id
from saki_api.db.session import get_session
from saki_api.models.user import User


async def get_current_user(
        session: AsyncSession = Depends(get_session)
) -> User:
    """
    获取当前认证用户。
    
    完全基于中间件设置的 ContextVar 获取用户信息。
    中间件已经从请求头中提取并验证了 token，并将用户 ID 设置到上下文变量中。
    
    Raises:
        HTTPException: 如果用户未认证或用户不存在/未激活
    """
    # 从上下文变量中获取用户 ID（中间件已设置）
    user_id = get_current_user_id()

    if not user_id:
        # 如果上下文变量中没有用户 ID，说明 token 无效或未提供
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 从数据库获取用户对象
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    return user


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
