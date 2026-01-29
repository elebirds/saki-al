"""
Service dependencies for FastAPI dependency injection.

Provides factory functions to create service instances with dependencies.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.deps import get_session, get_current_user
from saki_api.core.rbac import get_permission_checker, PermissionChecker
from saki_api.models.user import User
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_repository import UserRepository
from saki_api.repositories.user_system_role_repository import UserSystemRoleRepository
from saki_api.services.auth_service import AuthService
from saki_api.services.guards.admin_guard import AdminGuard, get_admin_guard
from saki_api.services.role_service import RoleService
from saki_api.services.system_service import SystemService
from saki_api.services.user_system_role_service import UserRoleService
from saki_api.services.user_service import UserService


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
# Guard Dependencies
# ============================================================================

# Type alias for AdminGuard dependency
AdminGuardDep = Annotated[AdminGuard, Depends(get_admin_guard)]
