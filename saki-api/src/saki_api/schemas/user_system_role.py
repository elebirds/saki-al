# ============================================================================
# User System Role Schemas
# ============================================================================
from typing import Optional
from saki_api.models.base import UUIDMixin, AuditMixin, TimestampMixin
from saki_api.models.rbac.user_system_role import UserSystemRoleBase


class UserSystemRoleCreate(UserSystemRoleBase):
    pass


class UserSystemRoleRead(UserSystemRoleBase, UUIDMixin, AuditMixin, TimestampMixin):
    """Schema for reading a user's system role."""

    # Include role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
