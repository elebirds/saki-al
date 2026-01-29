"""
Saki API Schemas

This module exports all Pydantic schemas used for API request/response models.
Schemas are separated from SQLModel database models for clear separation of concerns.
"""

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

from saki_api.schemas.user_system_role import (
    UserSystemRoleCreate,
    UserSystemRoleRead
)

# User Schemas
from saki_api.schemas.user import (
    UserCreate,
    UserRead,
    UserUpdate,
    UserReadWithPermissions,
    UserListItem,
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
    "ResourceMemberCreate",
    "ResourceMemberRead",

    # User Schemas
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserReadWithPermissions",
    "UserListItem",
]
