from typing import Any, List

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from app.api import deps
from app.core import security
from app.models.user import User, UserCreate, UserRead, UserUpdate

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
    current_user: User = Depends(deps.get_current_active_superuser),
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
    current_user: User = Depends(deps.get_current_active_superuser),
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
    current_user: User = Depends(deps.get_current_active_superuser),
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
    current_user: User = Depends(deps.get_current_active_superuser),
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
    session.delete(user)
    session.commit()
    return user
