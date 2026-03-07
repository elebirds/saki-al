# ============================================================================
# User System Role Schemas
# ============================================================================
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel

from saki_api.modules.access.domain.rbac.user_system_role import UserSystemRoleBase
from saki_api.modules.shared.modeling.base import UUIDMixin, AuditMixin, TimestampMixin


class UserSystemRoleAssign(SQLModel):
    """Schema for assigning a role to a user.
    
    Note: user_id is provided in the URL path, so it's not included here.
    """
    role_id: uuid.UUID
    expires_at: Optional[datetime] = None


class UserSystemRoleCreate(SQLModel):
    """Schema for creating a user system role assignment (internal use).
    
    This includes user_id and is used internally by the service layer.
    """
    user_id: uuid.UUID
    role_id: uuid.UUID
    expires_at: Optional[datetime] = None


class UserSystemRoleRead(UserSystemRoleBase, UUIDMixin, AuditMixin, TimestampMixin):
    """Schema for reading a user's system role."""

    # Include role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
