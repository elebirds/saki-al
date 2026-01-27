"""
FastAPI 中间件。

用于在请求处理过程中设置上下文变量。
"""
import logging
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from saki_api.core.config import settings
from saki_api.core.context import set_current_user_id
from saki_api.db.session import SessionLocal
from saki_api.models.user import User

logger = logging.getLogger(__name__)

# HTTPBearer 用于从请求头中提取 token，auto_error=False 表示没有 token 时不抛出异常
security = HTTPBearer(auto_error=False)


class AuditContextMiddleware(BaseHTTPMiddleware):
    """
    审计上下文中间件。
    
    在请求处理前提取 token，解析用户信息，并设置当前用户 ID 到 ContextVar，
    以便 SQLAlchemy 事件监听器使用。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求，提取 token 并设置用户上下文。
        
        Args:
            request: FastAPI 请求对象
            call_next: 下一个中间件或路由处理器
            
        Returns:
            HTTP 响应
        """
        # 初始化上下文变量
        set_current_user_id(None)

        # 尝试从请求头中提取 token
        authorization: Optional[HTTPAuthorizationCredentials] = await security(request)

        if authorization:
            token = authorization.credentials
            try:
                # 解析 token
                payload = jwt.decode(
                    token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
                )
                token_data = payload.get("sub")

                if token_data:
                    # 从数据库获取用户信息
                    async with SessionLocal() as session:
                        try:
                            user = await session.get(User, token_data)
                            if user and user.is_active:
                                # 设置当前用户 ID 到上下文变量
                                set_current_user_id(user.id)
                                logger.debug(f"User context set: {user.id}")
                            else:
                                logger.debug(f"User not found or inactive: {token_data}")
                        except Exception as e:
                            logger.warning(f"Error fetching user from database: {e}")
                        finally:
                            await session.close()
            except (JWTError, ValidationError) as e:
                # Token 无效，但不抛出异常，让依赖注入函数处理
                logger.debug(f"Invalid token: {e}")

        try:
            response = await call_next(request)
            return response
        finally:
            # 请求结束后清理上下文变量
            set_current_user_id(None)
