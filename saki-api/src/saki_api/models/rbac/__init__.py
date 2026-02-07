"""
RBAC (Role-Based Access Control) Models

This module provides a comprehensive RBAC system with:
- Dynamic role management (system and resource roles)
- Permission scopes (all, owned, assigned, self)
- Role inheritance
- Audit logging
"""

from saki_api.models.rbac.audit_log import (
    AuditLog,
)
from saki_api.models.rbac.enums import (
    RoleType,
    ResourceType,
    Scope,
    AuditAction,
    Permissions,
)
from saki_api.models.rbac.permission import (
    Permission,
    parse_permission,
)
from saki_api.models.rbac.resource_member import (
    ResourceMember,
)
from saki_api.models.rbac.role import (
    Role,
    RolePermission,
)
from saki_api.models.rbac.user_system_role import (
    UserSystemRole,
)

# Note: Schema classes are imported from saki_api.schemas.rbac
# They are re-exported through saki_api.models for backward compatibility

__all__ = [
    # Enums
    "RoleType",
    "ResourceType",
    "Scope",
    "AuditAction",
    "Permissions",
    # Permission class
    "Permission",
    "parse_permission",
    # Models only - schemas are in saki_api.schemas.rbac
    "Role",
    "RolePermission",
    "UserSystemRole",
    "ResourceMember",
    "AuditLog",
]
