"""
Saki API Schemas

This module exports all Pydantic schemas used for API request/response models.
Schemas are separated from SQLModel database models for clear separation of concerns.
"""

from saki_api.schemas.pagination import PaginationResponse
from saki_api.schemas.permission import (
    SystemPermissionsResponse,
    ResourcePermissionsResponse,
)
# RBAC Schemas
from saki_api.schemas.resource_member import (
    ResourceMemberCreate,
    ResourceMemberRead,
)
from saki_api.schemas.role import (
    RoleCreate,
    RoleRead,
    RoleUpdate,
    RoleReadMinimal
)
from saki_api.schemas.role_permission import (
    RolePermissionCreate,
    RolePermissionRead,
    RolePermissionUpdate,
)
# User Schemas
from saki_api.schemas.user import (
    UserCreate,
    UserRead,
    UserUpdate,
    UserReadWithPermissions,
    UserListItem,
)
from saki_api.schemas.user_system_role import (
    UserSystemRoleCreate,
    UserSystemRoleRead,
    UserSystemRoleAssign
)
from saki_api.schemas.l3.job import (
    JobCreateRequest,
    JobRead,
    JobCommandResponse,
)

__all__ = [
    # RBAC Schemas
    "RoleCreate",
    "RoleRead",
    "RoleUpdate",
    "RoleReadMinimal",
    "RolePermissionCreate",
    "RolePermissionRead",
    "RolePermissionUpdate",
    "UserSystemRoleCreate",
    "UserSystemRoleRead",
    "UserSystemRoleAssign",
    "ResourceMemberCreate",
    "ResourceMemberRead",

    # L3 Job Schemas
    "JobCreateRequest",
    "JobRead",
    "JobCommandResponse",

    # User Schemas
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserReadWithPermissions",
    "UserListItem",

    # Permission Query Schemas
    "SystemPermissionsResponse",
    "ResourcePermissionsResponse",

    # Pagination
    "PaginationResponse",
]
