from typing import Optional

from saki_api.models.base import UUIDMixin
from saki_api.models.rbac.resource_member import ResourceMemberBase


# ============================================================================
# Resource Member Schemas
# ============================================================================

class ResourceMemberCreate(ResourceMemberBase):
    pass

class ResourceMemberRead(ResourceMemberBase, UUIDMixin):
    """Schema for reading a resource member."""

    # User details
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None

    # Role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
