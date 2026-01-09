"""
FastAPI Dependencies for RBAC

Provides dependency injection for permission checking.
"""

from typing import Optional, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlmodel import Session

from saki_api.core.config import settings
from saki_api.db.session import get_session
from saki_api.models.user import User
from saki_api.core.rbac.checker import PermissionChecker

# OAuth2 scheme - duplicated here to avoid circular import
_reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token"
)


def _get_current_user_internal(
        session: Session = Depends(get_session),
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
    user = session.get(User, token_data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_permission_checker(
    session: Session = Depends(get_session)
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
    """
    
    def __init__(
        self,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id_param: Optional[str] = None,
        get_resource_owner: Optional[Callable[[Session, str], Optional[str]]] = None,
    ):
        """
        Initialize the permission dependency.
        
        Args:
            permission: Required permission (e.g., "dataset:read", "annotation:update:self")
            resource_type: Type of resource being accessed (string like "dataset")
            resource_id_param: URL path parameter name for resource ID
            get_resource_owner: Function to get resource owner ID
        """
        self.permission = permission
        self.resource_type = resource_type
        self.resource_id_param = resource_id_param
        self.get_resource_owner = get_resource_owner
    
    def __call__(
        self,
        request: Request,
        session: Session = Depends(get_session),
        current_user: User = Depends(_get_current_user_internal),
    ) -> User:
        """Check permission and return current user if authorized."""
        checker = PermissionChecker(session)
        
        # Build context
        resource_id = None
        resource_owner_id = None
        
        if self.resource_id_param:
            resource_id = request.path_params.get(self.resource_id_param)
        
        if self.get_resource_owner and resource_id:
            resource_owner_id = self.get_resource_owner(session, resource_id)
        
        if not checker.check(
            user_id=current_user.id,
            permission=self.permission,
            resource_type=self.resource_type,
            resource_id=resource_id,
            resource_owner_id=resource_owner_id,
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
    get_resource_owner: Optional[Callable[[Session, str], Optional[str]]] = None,
) -> PermissionDependency:
    """
    Create a permission checking dependency.
    
    Args:
        permission: Required permission string
        resource_type: Type of resource (for resource-level permissions)
        resource_id_param: URL parameter name containing the resource ID
        get_resource_owner: Function to retrieve resource owner ID
    
    Examples:
        # Simple permission check (system level)
        @router.get("/users")
        def list_users(
            current_user: User = Depends(require_permission("user:read")),
        ):
            ...
        
        # Resource-level permission check
        @router.get("/datasets/{dataset_id}")
        def get_dataset(
            dataset_id: str,
            current_user: User = Depends(require_permission(
                "dataset:read",
                "dataset",
                "dataset_id",
                get_dataset_owner
            )),
        ):
            ...
    """
    return PermissionDependency(
        permission=permission,
        resource_type=resource_type,
        resource_id_param=resource_id_param,
        get_resource_owner=get_resource_owner,
    )


# ============================================================================
# Helper Functions
# ============================================================================

def get_dataset_owner(session: Session, dataset_id: str) -> Optional[str]:
    """Get the owner ID of a dataset."""
    from saki_api.models import Dataset
    dataset = session.get(Dataset, dataset_id)
    return dataset.owner_id if dataset else None


def get_sample_dataset_owner(session: Session, sample_id: str) -> Optional[str]:
    """Get the owner ID of a sample's parent dataset."""
    from saki_api.models import Sample, Dataset
    sample = session.get(Sample, sample_id)
    if sample:
        dataset = session.get(Dataset, sample.dataset_id)
        return dataset.owner_id if dataset else None
    return None
