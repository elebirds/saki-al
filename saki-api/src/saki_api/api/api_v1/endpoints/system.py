"""
System endpoints for initialization and configuration.

Includes system setup, status check, and available types.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from saki_api.core import security
from saki_api.core.rbac.presets import init_preset_roles, get_role_by_name
from saki_api.db.session import get_session
from saki_api.models import (
    User, UserCreate, UserRead,
    UserSystemRole,
    Role,
)
from saki_api.models.enums import TaskType, AnnotationSystemType

router = APIRouter()


# ============================================================================
# Pydantic Models for API
# ============================================================================

class TypeInfo(BaseModel):
    """Information about a type option."""
    value: str
    label: str
    description: str


class AvailableTypesResponse(BaseModel):
    """Response with all available types."""
    task_types: List[TypeInfo]
    annotation_systems: List[TypeInfo]


# ============================================================================
# Type Definitions
# ============================================================================

TASK_TYPE_INFO = {
    TaskType.CLASSIFICATION: TypeInfo(
        value="classification",
        label="Classification",
        description="Image classification task - assign one label per image"
    ),
    TaskType.DETECTION: TypeInfo(
        value="detection",
        label="Detection",
        description="Object detection task - locate and classify objects with bounding boxes"
    ),
    TaskType.SEGMENTATION: TypeInfo(
        value="segmentation",
        label="Segmentation",
        description="Semantic segmentation task - pixel-level classification"
    ),
}

ANNOTATION_SYSTEM_INFO = {
    AnnotationSystemType.CLASSIC: TypeInfo(
        value="classic",
        label="Classic Annotation",
        description="Standard image annotation with rectangles and OBB"
    ),
    AnnotationSystemType.FEDO: TypeInfo(
        value="fedo",
        label="FEDO Dual-View",
        description="Satellite electron energy data annotation with Time-Energy and L-ωd synchronized views"
    ),
}


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/status")
def get_system_status(
        session: Session = Depends(get_session),
) -> Any:
    """
    Check if the system is initialized (has at least one user).
    """
    user = session.exec(select(User).limit(1)).first()
    return {"initialized": user is not None}


@router.get("/types", response_model=AvailableTypesResponse)
def get_available_types() -> AvailableTypesResponse:
    """
    Get all available task types and annotation systems.
    Frontend should call this to populate dropdowns.
    """
    return AvailableTypesResponse(
        task_types=[info for info in TASK_TYPE_INFO.values()],
        annotation_systems=[info for info in ANNOTATION_SYSTEM_INFO.values()],
    )


@router.post("/setup", response_model=UserRead)
def setup_system(
        user_in: UserCreate,
        session: Session = Depends(get_session),
) -> Any:
    """
    Initialize the system with the first superuser.
    
    This endpoint:
    1. Creates all preset roles
    2. Creates the first user
    3. Assigns super_admin role to the first user
    """
    user = session.exec(select(User).limit(1)).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="System already initialized",
        )

    # Initialize preset roles
    roles = init_preset_roles(session)

    # Create user
    user_data = user_in.model_dump(exclude={"password"})
    user_data["hashed_password"] = security.get_password_hash(user_in.password)
    user_data["is_active"] = True
    db_user = User.model_validate(user_data)
    session.add(db_user)
    session.flush()

    # Assign super_admin role
    super_admin_role = roles.get("super_admin")
    if not super_admin_role:
        super_admin_role = get_role_by_name(session, "super_admin")

    if super_admin_role:
        user_role = UserSystemRole(
            user_id=db_user.id,
            role_id=super_admin_role.id,
        )
        session.add(user_role)

    session.commit()
    session.refresh(db_user)

    # Build response
    return _build_user_read(db_user, session)


def _build_user_read(user: User, session: Session) -> UserRead:
    """Build UserRead with role information."""
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
