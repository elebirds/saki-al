from saki_api.modules.access.domain.rbac.role_permission import RolePermissionBase
from saki_api.modules.shared.modeling.base import UUIDMixin


# ============================================================================
# Role Permission Schemas
# ============================================================================

class RolePermissionCreate(RolePermissionBase):
    pass


class RolePermissionRead(RolePermissionBase, UUIDMixin):
    pass


class RolePermissionUpdate(RolePermissionBase):
    pass
