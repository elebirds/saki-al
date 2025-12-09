from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.db.session import get_session
from app.models.user import User, UserCreate, UserRead
from app.core import security

router = APIRouter()

@router.get("/status")
def get_system_status(
    session: Session = Depends(get_session),
) -> Any:
    """
    Check if the system is initialized (has at least one user).
    """
    user = session.exec(select(User).limit(1)).first()
    return {"initialized": user is not None}

@router.post("/setup", response_model=UserRead)
def setup_system(
    user_in: UserCreate,
    session: Session = Depends(get_session),
) -> Any:
    """
    Initialize the system with the first superuser.
    """
    user = session.exec(select(User).limit(1)).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="System already initialized",
        )
    
    user = User.from_orm(user_in)
    user.hashed_password = security.get_password_hash(user_in.password)
    user.is_superuser = True
    user.is_active = True
    
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
