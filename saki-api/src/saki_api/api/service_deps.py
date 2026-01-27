"""
Service dependencies for FastAPI dependency injection.

Provides factory functions to create service instances with dependencies.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.deps import get_session, get_current_user
from saki_api.models import User
from saki_api.services.role_service import RoleService
from saki_api.services.user_service import UserService


# ============================================================================
# User Service Dependencies
# ============================================================================

def get_user_service(
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user)
) -> UserService:
    """Get UserService with dependencies injected."""
    return UserService(session=session, current_user=current_user)


# Type alias for cleaner route signatures
UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# ============================================================================
# Role Service Dependencies
# ============================================================================

def get_role_service(
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user)
) -> RoleService:
    """Get RoleService with dependencies injected."""
    return RoleService(session=session, current_user=current_user)


# Type alias for cleaner route signatures
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]
