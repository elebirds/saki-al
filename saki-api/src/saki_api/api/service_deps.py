"""
Service dependencies for FastAPI dependency injection.

Provides factory functions to create service instances with dependencies.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.db.session import get_session
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.user import UserRepository
from saki_api.repositories.user_system_role import UserSystemRoleRepository
from saki_api.services.auth import AuthService
from saki_api.services.permission_query import PermissionQueryService
from saki_api.services.role import RoleService
from saki_api.services.system import SystemService
from saki_api.services.user import UserService
from saki_api.services.user_system_role import UserRoleService


# ============================================================================
# User Service Dependencies
# ============================================================================

def get_user_service(
        session: AsyncSession = Depends(get_session),
) -> UserService:
    """Get UserService with dependencies injected."""
    return UserService(session=session)


# Type alias for cleaner route signatures
UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# ============================================================================
# User Role Service Dependencies
# ============================================================================

def get_user_repository(
        session: AsyncSession = Depends(get_session),
) -> UserRepository:
    """Get UserRepository with dependencies injected."""
    return UserRepository(session)


def get_role_repository(
        session: AsyncSession = Depends(get_session),
) -> RoleRepository:
    """Get RoleRepository with dependencies injected."""
    return RoleRepository(session)


def get_user_role_repository(
        session: AsyncSession = Depends(get_session),
) -> UserSystemRoleRepository:
    """Get UserRoleRepository with dependencies injected."""
    return UserSystemRoleRepository(session)


def get_user_role_service(
        session: AsyncSession = Depends(get_session),
) -> UserRoleService:
    """Get UserRoleService with dependencies injected."""
    return UserRoleService(session=session)


# Type alias for cleaner route signatures
UserRoleServiceDep = Annotated[UserRoleService, Depends(get_user_role_service)]


# ============================================================================
# Role Service Dependencies
# ============================================================================

def get_role_service(
        session: AsyncSession = Depends(get_session),
) -> RoleService:
    """Get RoleService with dependencies injected."""
    return RoleService(session=session)


# Type alias for cleaner route signatures
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]


# ============================================================================
# System Service Dependencies
# ============================================================================

def get_system_service(
        session: AsyncSession = Depends(get_session),
) -> SystemService:
    return SystemService(session=session)


# Type alias for cleaner route signatures
SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]


# ============================================================================
# Auth Service Dependencies
# ============================================================================

def get_auth_service(
        session: AsyncSession = Depends(get_session),
) -> AuthService:
    return AuthService(session=session)


# Type alias for cleaner route signatures
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# ============================================================================
# Permission Query Service Dependencies
# ============================================================================

def get_permission_query_service(
        session: AsyncSession = Depends(get_session),
) -> PermissionQueryService:
    """Get PermissionQueryService with dependencies injected."""
    return PermissionQueryService(session=session)


# Type alias for cleaner route signatures
PermissionQueryServiceDep = Annotated[PermissionQueryService, Depends(get_permission_query_service)]
