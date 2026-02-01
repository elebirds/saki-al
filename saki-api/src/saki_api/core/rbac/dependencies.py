"""
FastAPI Dependencies for RBAC

Provides dependency injection for permission checking.
"""

import uuid
from typing import Optional, Callable, AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.context import set_current_user_id, reset_current_user_id
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.db.session import get_session
from saki_api.models.user import User
from saki_api.repositories.user import UserRepository

# HTTPBearer 用于从请求头中提取 token，并集成到 Swagger UI
security = HTTPBearer()


class TokenPayload(BaseModel):
    """JWT Token Payload 模型"""
    sub: str  # Subject (user ID)


async def get_token_payload(
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenPayload:
    """
    获取并解码 JWT Token，不访问数据库。
    
    这是最轻量级的依赖项，只解析 Token 获取 payload。
    用于 Swagger UI 的 Authorize 锁定功能。
    
    Args:
        credentials: HTTPBearer 自动提取的认证凭证
        
    Returns:
        TokenPayload: 解码后的 token payload
        
    Raises:
        HTTPException: 如果 token 无效或过期
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        return token_data
    except (JWTError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user_id(
        token_data: TokenPayload = Depends(get_token_payload)
) -> AsyncGenerator[uuid.UUID, None]:
    """
    获取当前用户 ID（轻量级依赖项）。
    
    依赖 get_token_payload，提取 sub 并注入 ContextVar。
    这是最快路径，用于只需要 ID 的场景（如 AuditMixin）。
    
    使用 yield 模式确保在请求结束后清理上下文变量。
    
    Args:
        token_data: 从 get_token_payload 获取的 token payload
        
    Returns:
        uuid.UUID: 当前用户 ID
        
    Yields:
        uuid.UUID: 当前用户 ID
    """
    user_id = uuid.UUID(token_data.sub)
    token = set_current_user_id(user_id)
    try:
        yield user_id
    finally:
        reset_current_user_id(token)


async def get_current_user(
        user_id: uuid.UUID = Depends(get_current_user_id),
        session: AsyncSession = Depends(get_session)
) -> User:
    """
    获取当前认证用户（深度依赖项）。
    
    依赖 get_current_user_id，查询数据库获取完整 User 对象。
    用于需要完整用户信息的场景。
    
    Args:
        user_id: 从 get_current_user_id 获取的用户 ID
        session: 数据库会话
        
    Returns:
        User: 当前用户对象
        
    Raises:
        HTTPException: 如果用户不存在或未激活
    """
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
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


class PermissionDependency:
    def __init__(
            self,
            permission: str,
            resource_type: Optional[str] = None,
            resource_id_param: Optional[str] = None,
    ):
        """
        Initialize the permission dependency.
        
        Args:
            permission: Required permission (e.g., "dataset:read", "annotation:modify:self")
            resource_type: Type of resource being accessed (string like "dataset")
            resource_id_param: URL path parameter name for resource ID
        """
        self.permission = permission
        self.resource_type = resource_type
        self.resource_id_param = resource_id_param

    async def __call__(
            self,
            request: Request,
            session: AsyncSession = Depends(get_session),
            user_id: uuid.UUID = Depends(get_current_user_id),
    ):
        """Check permission and return current user if authorized."""

        # Build context
        resource_id = None
        resource_type_enum = None

        if self.resource_id_param:
            resource_id = request.path_params.get(self.resource_id_param)

        # Convert resource_type string to ResourceType enum if provided
        if self.resource_type:
            try:
                from saki_api.models.rbac import ResourceType
                resource_type_enum = ResourceType(self.resource_type)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid resource type: {self.resource_type}"
                )

        checker = PermissionChecker(session)

        if not await checker.check(
                user_id=user_id,
                permission=self.permission,
                resource_type=resource_type_enum,
                resource_id=resource_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISSION_DENIED",
                    "message": f"Permission denied: {self.permission}",
                    "required_permission": self.permission,
                }
            )


def require_permission(
        permission: str,
        resource_type: Optional[str] = None,
        resource_id_param: Optional[str] = None,
        get_parent_resource_id: Optional[Callable[[AsyncSession, str], Optional[str]]] = None,
) -> PermissionDependency:
    return PermissionDependency(
        permission=permission,
        resource_type=resource_type,
        resource_id_param=resource_id_param
    )


# ============================================================================
# Parent Resource ID Getters (for sub-resources)
# ============================================================================

async def get_sample_dataset_id(session: AsyncSession, sample_id: str) -> Optional[str]:
    """Get the dataset ID of a sample."""
    from saki_api.models import Sample
    from saki_api.repositories.base import BaseRepository

    try:
        sample_uuid = uuid.UUID(sample_id)
    except ValueError:
        return None

    # Use repository pattern instead of direct session access
    sample_repo = BaseRepository(Sample, session)
    sample = await sample_repo.get_by_id(sample_uuid)
    return str(sample.dataset_id) if sample and sample.dataset_id else None


async def get_label_dataset_id(session: AsyncSession, label_id: str) -> Optional[str]:
    """
    Get the dataset ID of a label.
    
    Note: Label belongs to Project, not directly to Dataset.
    This function may need to be updated based on your actual data model.
    If labels don't have a direct dataset relationship, this should return None
    or be refactored to get dataset through project.
    """
    from saki_api.models import Label
    from saki_api.repositories.base import BaseRepository

    try:
        label_uuid = uuid.UUID(label_id)
    except ValueError:
        return None

    # Use repository pattern instead of direct session access
    label_repo = BaseRepository(Label, session)
    label = await label_repo.get_by_id(label_uuid)

    # Note: Label model has project_id, not dataset_id
    # If you need dataset_id, you may need to join through project
    # For now, return None as labels don't directly belong to datasets
    return None
