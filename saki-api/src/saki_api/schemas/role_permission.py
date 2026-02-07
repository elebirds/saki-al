from saki_api.models.base import UUIDMixin
from saki_api.models.rbac.role_permission import RolePermissionBase


# ============================================================================
# Role Permission Schemas
# ============================================================================

class RolePermissionCreate(RolePermissionBase):
    pass


class RolePermissionRead(RolePermissionBase, UUIDMixin):
    pass


class RolePermissionUpdate(RolePermissionBase):
    pass
