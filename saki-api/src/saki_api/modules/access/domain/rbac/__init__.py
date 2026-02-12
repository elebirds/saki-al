"""
RBAC (Role-Based Access Control) Models

This module provides a comprehensive RBAC system with:
- Dynamic role management (system and resource roles)
- Permission scopes (all, owned, assigned, self)
- Role inheritance
- Audit logging
"""

from saki_api.modules.access.domain.rbac.audit_log import (
    AuditLog,
)
from saki_api.modules.access.domain.rbac.enums import (
    RoleType,
    ResourceType,
    Scope,
    AuditAction,
    Permissions,
)
from saki_api.modules.access.domain.rbac.permission import (
    Permission,
    parse_permission,
)
from saki_api.modules.access.domain.rbac.resource_member import (
    ResourceMember,
)
from saki_api.modules.access.domain.rbac.role import (
    Role,
    RolePermission,
)
from saki_api.modules.access.domain.rbac.user_system_role import (
    UserSystemRole,
)

# Note: API schema classes live under modules/*/api packages.

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
