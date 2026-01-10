"""
API endpoints for User management.

Uses the new RBAC system for permission checking.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from saki_api.api.deps import get_current_user, get_session
from saki_api.core import security
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
)
from saki_api.core.rbac.presets import get_default_role
from saki_api.models import (
    User, UserCreate, UserRead, UserUpdate, UserListItem,
    Role, UserSystemRole,
    Permissions,
)

router = APIRouter()


@router.get("/me", response_model=UserRead)
def read_user_me(
        session: Session = Depends(get_session),
        current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get current user.
    """
    return _build_user_read(current_user, session)


@router.get("/list", response_model=List[UserListItem])
def list_users_simple(
        session: Session = Depends(get_session),
        skip: int = 0,
        limit: int = 100,
        current_user: User = Depends(require_permission(Permissions.USER_LIST)),
) -> Any:
    """
    List users with basic info only (for member selection).
    
    Requires user:list permission (not full user:read).
    """
    users = session.exec(select(User).where(User.is_active == True).offset(skip).limit(limit)).all()
    return [
        UserListItem(id=u.id, email=u.email, full_name=u.full_name)
        for u in users
    ]


@router.get("/", response_model=List[UserRead])
def read_users(
        session: Session = Depends(get_session),
        skip: int = 0,
        limit: int = 100,
        current_user: User = Depends(require_permission(Permissions.USER_READ)),
) -> Any:
    """
    Retrieve users with full details.
    
    Requires user:read permission (admin level).
    """
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return [_build_user_read(u, session) for u in users]


@router.post("/", response_model=UserRead)
def create_user(
        *,
        session: Session = Depends(get_session),
        user_in: UserCreate,
        current_user: User = Depends(require_permission(Permissions.USER_CREATE))
) -> Any:
    """
    Create new user.
    """
    user = session.exec(select(User).where(User.email == user_in.email)).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )

    # Hash password
    hashed_password = security.get_password_hash(user_in.password)

    user_data = user_in.model_dump(exclude={"password"})
    # Manually created users must change password on first login
    db_user = User(**user_data, hashed_password=hashed_password, must_change_password=True)

    session.add(db_user)
    session.flush()

    # Assign default role
    default_role = get_default_role(session)
    if default_role:
        user_role = UserSystemRole(
            user_id=db_user.id,
            role_id=default_role.id,
            assigned_by=current_user.id,
        )
        session.add(user_role)

    session.commit()
    session.refresh(db_user)
    return _build_user_read(db_user, session)


@router.put("/{user_id}", response_model=UserRead)
def update_user(
        *,
        session: Session = Depends(get_session),
        user_id: str,
        user_in: UserUpdate,
        current_user: User = Depends(require_permission(Permissions.USER_UPDATE)),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> Any:
    """
    Update a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )

    user_data = user_in.model_dump(exclude_unset=True)

    # Protect super admin
    if checker.is_super_admin(user.id):
        if not checker.is_super_admin(current_user.id):
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can modify super administrator accounts"
            )

    if "password" in user_data:
        password = user_data.pop("password")
        if password:
            user_data["hashed_password"] = security.get_password_hash(password)

    for key, value in user_data.items():
        setattr(user, key, value)

    session.add(user)
    session.commit()
    session.refresh(user)
    return _build_user_read(user, session)


@router.delete("/{user_id}", response_model=UserRead)
def delete_user(
        *,
        session: Session = Depends(get_session),
        user_id: str,
        current_user: User = Depends(require_permission(Permissions.USER_DELETE)),
        checker: PermissionChecker = Depends(get_permission_checker),
) -> Any:
    """
    Delete a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )

    # Protect super admin
    if checker.is_super_admin(user.id):
        if not checker.is_super_admin(current_user.id):
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can delete super administrator accounts"
            )
        if user_id == current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Super administrators cannot delete themselves"
            )

    result = _build_user_read(user, session)
    session.delete(user)
    session.commit()
    return result


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
