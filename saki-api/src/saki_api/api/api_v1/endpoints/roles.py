"""
API endpoints for Role management.

Provides CRUD operations for roles and user role assignments.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.deps import get_session
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
)
from saki_api.models import User, RoleType, Permissions
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_repository import UserRepository
from saki_api.schemas import (
    RoleCreate, RoleRead, RoleUpdate,
    UserSystemRoleCreate, UserSystemRoleRead,
)
from saki_api.services.role_service import RoleService
from saki_api.services.user_service import UserService

router = APIRouter()


# ============================================================================
# Role CRUD
# ============================================================================

@router.get("/", response_model=List[RoleRead])
async def list_roles(
        type: Optional[RoleType] = Query(None, description="Filter by role type"),
        session: AsyncSession = Depends(get_session),
        _current_user: User = Depends(require_permission(Permissions.ROLE_READ)),
):
    """
    List all roles.
    
    Optionally filter by type (system or resource).
    """
    repo = RoleRepository(session)
    service = RoleService(repo)
    roles = await service.list_roles(role_type=type)
    return [await service.build_role_read(role) for role in roles]


@router.get("/{role_id}", response_model=RoleRead)
async def get_role(
        role_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        _current_user: User = Depends(require_permission(Permissions.ROLE_READ)),
):
    """Get a role by ID."""
    repo = RoleRepository(session)
    service = RoleService(repo)
    role = await service.get_by_id(role_id)
    return await service.build_role_read(role)


@router.post("/", response_model=RoleRead)
async def create_role(
        role_in: RoleCreate,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.ROLE_CREATE)),
):
    """
    Create a custom role.
    
    System preset roles cannot be created through this endpoint.
    """
    repo = RoleRepository(session)
    service = RoleService(repo)
    role = await service.create_role(role_in, current_user.id)
    return await service.build_role_read(role)


@router.put("/{role_id}", response_model=RoleRead)
async def update_role(
        role_id: uuid.UUID,
        role_in: RoleUpdate,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.ROLE_UPDATE)),
):
    """
    Update a role.
    
    System preset roles have limited update capabilities.
    """
    repo = RoleRepository(session)
    service = RoleService(repo)
    role = await service.update_role(role_id, role_in, current_user.id)
    return await service.build_role_read(role)


@router.delete("/{role_id}")
async def delete_role(
        role_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.ROLE_DELETE)),
):
    """
    Delete a role.
    
    System preset roles cannot be deleted.
    Roles that are in use cannot be deleted.
    """
    repo = RoleRepository(session)
    service = RoleService(repo)
    await service.delete_role(role_id, current_user.id)


# ============================================================================
# User Role Management
# ============================================================================

@router.get("/users/{user_id}/roles", response_model=List[UserSystemRoleRead])
async def get_user_roles(
        user_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        _current_user: User = Depends(require_permission(Permissions.USER_ROLE_READ)),
):
    """Get all system roles assigned to a user."""
    user_service = UserService(UserRepository(session))
    role_repo = RoleRepository(session)
    return await user_service.get_user_roles_read(user_id, role_repo)


@router.post("/users/{user_id}/roles", response_model=UserSystemRoleRead)
async def assign_user_role(
        user_id: uuid.UUID,
        role_in: UserSystemRoleCreate,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.ROLE_ASSIGN)),
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """Assign a system role to a user."""
    user_service = UserService(UserRepository(session))
    role_repo = RoleRepository(session)
    return await user_service.assign_user_system_role(
        user_id=user_id,
        role_in=role_in,
        current_user=current_user,
        checker=checker,
        role_repo=role_repo,
    )


@router.delete("/users/{user_id}/roles/{role_id}")
async def revoke_user_role(
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.ROLE_REVOKE)),
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """Revoke a system role from a user."""
    user_service = UserService(UserRepository(session))
    role_repo = RoleRepository(session)
    await user_service.revoke_user_system_role(
        user_id=user_id,
        role_id=role_id,
        current_user=current_user,
        checker=checker,
        role_repo=role_repo,
    )
