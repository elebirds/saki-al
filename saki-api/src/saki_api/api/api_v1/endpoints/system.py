from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from saki_api.core import security
from saki_api.db.session import get_session
from saki_api.models.enums import TaskType, AnnotationSystemType
from saki_api.models.user import User, UserCreate, UserRead
from sqlmodel import Session, select

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
    """
    user = session.exec(select(User).limit(1)).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="System already initialized",
        )

    from saki_api.models.permission import GlobalRole

    user_data = user_in.model_dump(exclude={"password"})
    user_data["hashed_password"] = security.get_password_hash(user_in.password)
    user_data["global_role"] = GlobalRole.SUPER_ADMIN  # Set as super admin
    user_data["is_active"] = True
    user = User.model_validate(user_data)

    session.add(user)
    session.commit()
    session.refresh(user)
    return user
