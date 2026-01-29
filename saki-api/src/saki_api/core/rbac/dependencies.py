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


async def get_permission_checker(
        session: AsyncSession = Depends(get_session)
) -> PermissionChecker:
    """Dependency to get a PermissionChecker instance."""
    return PermissionChecker(session)


class PermissionDependency:
    """
    Permission checking dependency for FastAPI.
    
    Usage:
        @router.get("/{dataset_id}")
        def get_dataset(
            dataset_id: str,
            current_user: User = Depends(require_permission("dataset:read", "dataset", "dataset_id")),
        ):
            ...
        
        # For sub-resources (label, annotation), use get_parent_resource_id:
        @router.get("/labels/{label_id}")
        def get_label(
            label_id: str,
            current_user: User = Depends(require_permission(
                "label:read:assigned", "dataset", "label_id",
                get_label_dataset_owner, get_label_dataset_id
            )),
        ):
            ...
    """

    def __init__(
            self,
            permission: str,
            resource_type: Optional[str] = None,
            resource_id_param: Optional[str] = None,
            get_parent_resource_id: Optional[Callable[[AsyncSession, str], Optional[str]]] = None,
    ):
        """
        Initialize the permission dependency.
        
        Args:
            permission: Required permission (e.g., "dataset:read", "annotation:modify:self")
            resource_type: Type of resource being accessed (string like "dataset")
            resource_id_param: URL path parameter name for resource ID
            get_parent_resource_id: Function to get parent resource ID (for sub-resources like label/annotation)
        """
        self.permission = permission
        self.resource_type = resource_type
        self.resource_id_param = resource_id_param
        self.get_parent_resource_id = get_parent_resource_id

    async def __call__(
            self,
            request: Request,
            session: AsyncSession = Depends(get_session),
            current_user: User = Depends(get_current_user),
    ) -> User:
        """Check permission and return current user if authorized."""
        checker = PermissionChecker(session)

        # Build context
        resource_id = None

        if self.resource_id_param:
            param_id = request.path_params.get(self.resource_id_param)

            # For sub-resources, get the parent resource ID
            if self.get_parent_resource_id and param_id:
                resource_id = await self.get_parent_resource_id(session, param_id)
            else:
                resource_id = param_id

        if not await checker.check(
                user_id=current_user.id,
                permission=self.permission,
                resource_type=self.resource_type,
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

        return current_user


def require_permission(
        permission: str,
        resource_type: Optional[str] = None,
        resource_id_param: Optional[str] = None,
        get_parent_resource_id: Optional[Callable[[AsyncSession, str], Optional[str]]] = None,
) -> PermissionDependency:
    """
    Create a permission checking dependency.
    
    Args:
        permission: Required permission string
        resource_type: Type of resource (for resource-level permissions)
        resource_id_param: URL parameter name containing the resource ID
        get_parent_resource_id: Function to get parent resource ID (for sub-resources)
    
    Examples:
        # Simple permission check (system level)
        @router.get("/users")
        def list_users(
            current_user: User = Depends(require_permission(Permissions.USER_READ)),
        ):
            ...
        
        # Resource-level permission check
        @router.get("/datasets/{dataset_id}")
        def get_dataset(
            dataset_id: str,
            current_user: User = Depends(require_permission(
                Permissions.DATASET_READ,
                ResourceType.DATASET,
                "dataset_id",
                get_dataset_owner
            )),
        ):
            ...
        
        # Sub-resource permission check (label -> dataset)
        @router.get("/labels/{label_id}")
        def get_label(
            label_id: str,
            current_user: User = Depends(require_permission(
                Permissions.LABEL_READ,
                ResourceType.DATASET,
                "label_id",
                get_label_dataset_id
            )),
        ):
            ...
    """
    return PermissionDependency(
        permission=permission,
        resource_type=resource_type,
        resource_id_param=resource_id_param,
        get_parent_resource_id=get_parent_resource_id,
    )


# ============================================================================
# Parent Resource ID Getters (for sub-resources)
# ============================================================================

async def get_sample_dataset_id(session: AsyncSession, sample_id: str) -> Optional[str]:
    """Get the dataset ID of a sample."""
    from saki_api.models import Sample
    sample = await session.get(Sample, sample_id)
    return sample.dataset_id if sample else None


async def get_label_dataset_id(session: AsyncSession, label_id: str) -> Optional[str]:
    """Get the dataset ID of a label."""
    from saki_api.models import Label
    label = await session.get(Label, label_id)
    return label.dataset_id if label else None
