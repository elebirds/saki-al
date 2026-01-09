"""
RBAC (Role-Based Access Control) Models

This module provides a comprehensive RBAC system with:
- Dynamic role management (system and resource roles)
- Permission scopes (all, owned, assigned, self)
- Role inheritance
- Audit logging
"""

from saki_api.models.rbac.enums import (
    RoleType,
    ResourceType,
    Scope,
    AuditAction,
    Resource,
    Action,
    Permissions,
    build_permission,
)
from saki_api.models.rbac.role import (
    Role,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    RolePermission,
    RolePermissionCreate,
    RolePermissionRead,
)
from saki_api.models.rbac.user_role import (
    UserSystemRole,
    UserSystemRoleCreate,
    UserSystemRoleRead,
)
from saki_api.models.rbac.resource_member import (
    ResourceMember,
    ResourceMemberCreate,
    ResourceMemberRead,
    ResourceMemberUpdate,
)
from saki_api.models.rbac.audit_log import (
    AuditLog,
    AuditLogRead,
)

__all__ = [
    # Enums
    "RoleType",
    "ResourceType",
    "Scope",
    "AuditAction",
    "Resource",
    "Action",
    "Permissions",
    "build_permission",
    # Role
    "Role",
    "RoleCreate",
    "RoleRead",
    "RoleUpdate",
    "RolePermission",
    "RolePermissionCreate",
    "RolePermissionRead",
    # User System Role
    "UserSystemRole",
    "UserSystemRoleCreate",
    "UserSystemRoleRead",
    # Resource Member
    "ResourceMember",
    "ResourceMemberCreate",
    "ResourceMemberRead",
    "ResourceMemberUpdate",
    # Audit Log
    "AuditLog",
    "AuditLogRead",
]
