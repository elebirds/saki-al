"""
Saki API Schemas

This module exports all Pydantic schemas used for API request/response models.
Schemas are separated from SQLModel database models for clear separation of concerns.
"""

# RBAC Schemas
from saki_api.schemas.rbac import (
    RoleCreate,
    RoleRead,
    RoleUpdate,
    RolePermissionCreate,
    RolePermissionRead,
    UserSystemRoleCreate,
    UserSystemRoleRead,
    ResourceMemberCreate,
    ResourceMemberRead,
    ResourceMemberUpdate,
    AuditLogRead,
)

# User Schemas
from saki_api.schemas.user import (
    UserCreate,
    UserRead,
    UserUpdate,
    UserWithPermissions,
    UserListItem,
)

__all__ = [
    # RBAC Schemas
    "RoleCreate",
    "RoleRead",
    "RoleUpdate",
    "RolePermissionCreate",
    "RolePermissionRead",
    "UserSystemRoleCreate",
    "UserSystemRoleRead",
    "ResourceMemberCreate",
    "ResourceMemberRead",
    "ResourceMemberUpdate",
    "AuditLogRead",

    # User Schemas
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserWithPermissions",
    "UserListItem",
]
