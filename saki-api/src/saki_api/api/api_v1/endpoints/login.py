"""
Authentication and Authorization endpoints.

Provides login, registration, password management, and permission info.
"""

from datetime import datetime, timedelta
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.core import security
from saki_api.core.config import settings
from saki_api.core.rbac import (
    PermissionChecker,
    PermissionContext,
    get_permission_checker,
)
from saki_api.core.rbac.presets import get_default_role
from saki_api.db.session import get_session
from saki_api.models import (
    User, UserCreate, UserRead,
    Role, UserSystemRole,
    ResourceType,
)

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RoleInfo(BaseModel):
    """Basic role information."""
    id: str
    name: str
    displayName: str


class PermissionInfo(BaseModel):
    """Permission with scope."""
    permission: str
    scope: str


class UserPermissionsResponse(BaseModel):
    """Response for user permissions endpoint."""
    userId: str
    systemRoles: List[RoleInfo]
    resourceRole: Optional[RoleInfo] = None
    permissions: List[str]
    isSuperAdmin: bool
    isOwner: Optional[bool] = None


@router.post("/login/access-token")
def login_access_token(
        session: Session = Depends(get_session),
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    statement = select(User).where(User.email == form_data.username)
    user = session.exec(statement).first()

    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Update last login time
    user.last_login_at = datetime.utcnow()
    session.add(user)
    session.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    response = {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

    # Add must_change_password flag if needed
    if user.must_change_password:
        response["must_change_password"] = True

    return response


@router.post("/register", response_model=UserRead)
def register_user(
        user_in: UserCreate,
        session: Session = Depends(get_session),
) -> Any:
    """
    Create new user without the need to be logged in.
    
    New users are automatically assigned the default system role.
    """
    statement = select(User).where(User.email == user_in.email)
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system",
        )

    # Create user
    user_data = user_in.model_dump(exclude={"password"})
    user_data["hashed_password"] = security.get_password_hash(user_in.password)
    user = User.model_validate(user_data)
    session.add(user)
    session.flush()  # Get user ID

    # Assign default role
    default_role = get_default_role(session)
    if default_role:
        user_role = UserSystemRole(
            user_id=user.id,
            role_id=default_role.id,
        )
        session.add(user_role)

    session.commit()
    session.refresh(user)

    # Build response with roles
    return _build_user_read(user, session)


@router.post("/login/refresh-token")
def refresh_token(
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Refresh access token.
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
    Change user password.
    """
    # Verify old password
    if not security.verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")

    # Verify new password format
    if not security.is_frontend_hashed_password(password_data.new_password):
        raise HTTPException(
            status_code=400,
            detail="New password must be in the correct format (frontend hashed)"
        )

    # Update password
    current_user.hashed_password = security.get_password_hash(password_data.new_password)
    current_user.must_change_password = False

    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    return {"message": "Password changed successfully"}


@router.get("/permissions", response_model=UserPermissionsResponse)
def get_my_permissions(
        resource_type: Optional[str] = Query(None, description="Resource type (e.g., 'dataset')"),
        resource_id: Optional[str] = Query(None, description="Resource ID"),
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> UserPermissionsResponse:
    """
    Get current user's permissions.
    
    If resource_type and resource_id are provided, includes resource-specific
    permissions and role information.
    
    This endpoint is used by the frontend to determine what UI elements to show.
    """
    # Get system roles
    user_roles = session.exec(
        select(UserSystemRole).where(
            UserSystemRole.user_id == current_user.id,
            (UserSystemRole.expires_at == None) |
            (UserSystemRole.expires_at > datetime.utcnow())
        )
    ).all()

    system_roles = []
    for ur in user_roles:
        role = session.get(Role, ur.role_id)
        if role:
            system_roles.append(RoleInfo(
                id=role.id,
                name=role.name,
                displayName=role.display_name,
            ))

    # Check if super admin
    is_super_admin = checker.is_super_admin(current_user.id)

    # Get permissions
    ctx = PermissionContext(user_id=current_user.id)
    if resource_type and resource_id:
        try:
            rt = ResourceType(resource_type)
            ctx = PermissionContext(
                user_id=current_user.id,
                resource_type=rt,
                resource_id=resource_id,
            )
        except ValueError:
            pass

    permissions = checker.get_effective_permissions(ctx)

    # Get resource role if applicable
    resource_role = None
    is_owner = None

    if resource_type and resource_id:
        try:
            rt = ResourceType(resource_type)
            role = checker.get_user_role_in_resource(current_user.id, rt, resource_id)
            if role:
                resource_role = RoleInfo(
                    id=role.id,
                    name=role.name,
                    displayName=role.display_name,
                )

            # Check if owner
            if resource_type == "dataset":
                from saki_api.models import Dataset
                dataset = session.get(Dataset, resource_id)
                if dataset:
                    is_owner = dataset.owner_id == current_user.id
        except ValueError:
            pass

    return UserPermissionsResponse(
        userId=current_user.id,
        systemRoles=system_roles,
        resourceRole=resource_role,
        permissions=list(permissions),
        isSuperAdmin=is_super_admin,
        isOwner=is_owner,
    )


def _build_user_read(user: User, session: Session) -> UserRead:
    """Build UserRead with role information."""
    # Get system roles
    user_roles = session.exec(
        select(UserSystemRole).where(UserSystemRole.user_id == user.id)
    ).all()

    system_roles = []
    for ur in user_roles:
        role = session.get(Role, ur.role_id)
        if role:
            system_roles.append({
                "id": role.id,
                "name": role.name,
                "displayName": role.display_name,
            })

    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        system_roles=system_roles,
    )
