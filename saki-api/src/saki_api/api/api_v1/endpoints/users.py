from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from saki_api.api import deps
from saki_api.core import security
from saki_api.models.user import User, UserCreate, UserRead, UserUpdate
from saki_api.models.permission import Permission, GlobalRole
from saki_api.core.permissions import require_permission

router = APIRouter()


@router.get("/me", response_model=UserRead)
def read_user_me(
        current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get current user.
    """
    return current_user


@router.get("/", response_model=List[UserRead])
def read_users(
        session: Session = Depends(deps.get_session),
        skip: int = 0,
        limit: int = 100,
        current_user: User = Depends(require_permission(Permission.USER_READ)),
) -> Any:
    """
    Retrieve users.
    """
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users


@router.post("/", response_model=UserRead)
def create_user(
        *,
        session: Session = Depends(deps.get_session),
        user_in: UserCreate,
        current_user: User = Depends(require_permission(Permission.USER_CREATE)),
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

    # 保护：只有超级管理员可以创建超级管理员账户
    if user_in.global_role == GlobalRole.SUPER_ADMIN:
        if current_user.global_role != GlobalRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can create super administrator accounts"
            )

    # Hash password
    hashed_password = security.get_password_hash(user_in.password)

    user_data = user_in.dict(exclude={"password"})
    db_user = User(**user_data, hashed_password=hashed_password)

    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


@router.put("/{user_id}", response_model=UserRead)
def update_user(
        *,
        session: Session = Depends(deps.get_session),
        user_id: str,
        user_in: UserUpdate,
        current_user: User = Depends(require_permission(Permission.USER_UPDATE)),
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

    user_data = user_in.dict(exclude_unset=True)
    
    # 保护超级管理员：只有超级管理员可以修改超级管理员账户
    if user.global_role == GlobalRole.SUPER_ADMIN:
        if current_user.global_role != GlobalRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can modify super administrator accounts"
            )
        # 超级管理员不能修改自己的角色
        if user_id == current_user.id and "global_role" in user_data:
            if user_data["global_role"] != GlobalRole.SUPER_ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail="Super administrators cannot change their own role"
                )
    
    # Check if trying to modify global_role - requires USER_MANAGE_ROLES permission
    if "global_role" in user_data:
        from saki_api.core.permissions import check_permission
        if not check_permission(current_user, Permission.USER_MANAGE_ROLES, session=session):
            # Remove global_role from update if user doesn't have permission
            user_data.pop("global_role")
        # 防止将用户设置为超级管理员（只有超级管理员可以创建新的超级管理员）
        elif user_data["global_role"] == GlobalRole.SUPER_ADMIN and current_user.global_role != GlobalRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can assign super administrator role"
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
    return user


@router.delete("/{user_id}", response_model=UserRead)
def delete_user(
        *,
        session: Session = Depends(deps.get_session),
        user_id: str,
        current_user: User = Depends(require_permission(Permission.USER_DELETE)),
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
    
    # 保护超级管理员：只有超级管理员可以删除超级管理员，且不能删除自己
    if user.global_role == GlobalRole.SUPER_ADMIN:
        if current_user.global_role != GlobalRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can delete super administrator accounts"
            )
        if user_id == current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Super administrators cannot delete themselves"
            )
    
    session.delete(user)
    session.commit()
    return user
