from typing import Any, List, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from db.session import get_session
from models.user import User, UserCreate, UserRead
from models.enums import TaskType, AnnotationSystemType
from core import security

router = APIRouter()

# ============================================================================
# In-memory store for registered frontend capabilities
# ============================================================================

_registered_annotation_systems: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Pydantic Models for API
# ============================================================================

class TypeInfo(BaseModel):
    """Information about a type option."""
    value: str
    label: str
    description: str


class AnnotationSystemCapability(BaseModel):
    """Frontend capability registration for an annotation system."""
    system_type: str
    version: str
    features: List[str] = []
    client_id: str


class AvailableTypesResponse(BaseModel):
    """Response with all available types."""
    task_types: List[TypeInfo]
    annotation_systems: List[TypeInfo]


class RegisteredSystemsResponse(BaseModel):
    """Response with registered annotation system capabilities."""
    systems: Dict[str, Dict[str, Any]]


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


@router.post("/annotation-systems/register")
def register_annotation_system(
    capability: AnnotationSystemCapability,
) -> Dict[str, str]:
    """
    Register a frontend's annotation system capability.
    Frontend calls this on startup to report which systems it supports.
    """
    system_type = capability.system_type
    
    # Validate system type
    valid_types = [e.value for e in AnnotationSystemType]
    if system_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown annotation system type: {system_type}. Valid types: {valid_types}"
        )
    
    # Store the capability
    _registered_annotation_systems[capability.client_id] = {
        "system_type": system_type,
        "version": capability.version,
        "features": capability.features,
        "registered_at": "now",  # TODO: Use actual timestamp
    }
    
    return {"status": "registered", "client_id": capability.client_id}


@router.get("/annotation-systems/registered", response_model=RegisteredSystemsResponse)
def get_registered_systems() -> RegisteredSystemsResponse:
    """
    Get all registered annotation system capabilities from frontends.
    """
    return RegisteredSystemsResponse(systems=_registered_annotation_systems)


@router.delete("/annotation-systems/{client_id}")
def unregister_annotation_system(client_id: str) -> Dict[str, str]:
    """
    Unregister a frontend's annotation system capability.
    """
    if client_id in _registered_annotation_systems:
        del _registered_annotation_systems[client_id]
        return {"status": "unregistered", "client_id": client_id}
    raise HTTPException(status_code=404, detail=f"Client {client_id} not found")


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
    
    user_data = user_in.model_dump(exclude={"password"})
    user_data["hashed_password"] = security.get_password_hash(user_in.password)
    user_data["is_superuser"] = True
    user_data["is_active"] = True
    user = User.model_validate(user_data)
    
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
