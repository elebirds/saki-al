"""
RBAC Core Module

Provides permission checking, dependencies, and preset configurations.
"""

from saki_api.core.rbac.audit import (
    log_audit,
)
from saki_api.core.rbac.checker import (
    PermissionChecker,
    PermissionContext,
)
from saki_api.core.rbac.presets import (
    PRESET_ROLES,
    init_preset_roles,
)


# Lazy import for require_permission to avoid circular imports
def require_permission(*args, **kwargs):
    """Lazy import wrapper to avoid circular imports."""
    from saki_api.core.rbac.dependencies import require_permission as _require_permission
    return _require_permission(*args, **kwargs)


__all__ = [
    # Checker
    "PermissionChecker",
    "PermissionContext",
    # Dependencies
    "require_permission",
    # Presets
    "PRESET_ROLES",
    "init_preset_roles",
    # Audit
    "log_audit",
]
