"""
System endpoints for initialization and configuration.

Includes system setup, status check, and available types.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.db.session import get_session
from saki_api.models import User
from saki_api.schemas import UserCreate, UserRead
from saki_api.services.system_service import SystemService

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
# Endpoints
# ============================================================================

@router.get("/status")
async def get_system_status(
        session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Check if the system is initialized (has at least one user).
    """
    svc = SystemService(session)
    return await svc.get_status()


@router.get("/types", response_model=AvailableTypesResponse)
def get_available_types() -> AvailableTypesResponse:
    """
    Get all available task types and annotation systems.
    Frontend should call this to populate dropdowns.
    """
    data = SystemService.get_available_types()
    return AvailableTypesResponse(
        task_types=[TypeInfo(**item) for item in data["task_types"]],
        annotation_systems=[TypeInfo(**item) for item in data["annotation_systems"]],
    )


@router.post("/setup", response_model=UserRead)
async def setup_system(
        user_in: UserCreate,
        session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Initialize the system with the first superuser.
    
    This endpoint:
    1. Creates all preset roles
    2. Creates the first user
    3. Assigns super_admin role to the first user
    """
    # Disallow re-initialization
    result = await session.exec(select(User).limit(1))
    if result.first():
        raise HTTPException(status_code=400, detail="System already initialized")

    svc = SystemService(session)
    db_user = await svc.setup_system(user_in)
    return await svc.build_user_read(db_user)
