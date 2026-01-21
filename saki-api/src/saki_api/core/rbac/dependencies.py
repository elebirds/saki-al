"""
FastAPI Dependencies for RBAC

Provides dependency injection for permission checking.
"""

from typing import Optional, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.db.session import get_session
from saki_api.models.user import User

# OAuth2 scheme - duplicated here to avoid circular import
_reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token"
)


async def _get_current_user_internal(
        session: AsyncSession = Depends(get_session),
        token: str = Depends(_reusable_oauth2)
) -> User:
    """Internal user getter to avoid circular import."""
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
    user = await session.get(User, token_data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
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
            current_user: User = Depends(_get_current_user_internal),
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
