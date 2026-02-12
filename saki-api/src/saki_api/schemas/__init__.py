"""
Saki API Schemas

This module exports all Pydantic schemas used for API request/response models.
Schemas are separated from SQLModel database models for clear separation of concerns.
"""

from saki_api.schemas.common.pagination import PaginationResponse
from saki_api.schemas.access.permission import (
    SystemPermissionsResponse,
    ResourcePermissionsResponse,
)
# RBAC Schemas
from saki_api.schemas.access.resource_member import (
    ResourceMemberCreate,
    ResourceMemberRead,
)
from saki_api.schemas.access.role import (
    RoleCreate,
    RoleRead,
    RoleUpdate,
    RoleReadMinimal
)
from saki_api.schemas.access.role_permission import (
    RolePermissionCreate,
    RolePermissionRead,
    RolePermissionUpdate,
)
# User Schemas
from saki_api.schemas.access.user import (
    UserCreate,
    UserRead,
    UserUpdate,
    UserReadWithPermissions,
    UserListItem,
)
from saki_api.schemas.access.user_system_role import (
    UserSystemRoleCreate,
    UserSystemRoleRead,
    UserSystemRoleAssign
)
from saki_api.schemas.runtime.job import (
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
