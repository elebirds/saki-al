from typing import Optional, List

from sqlmodel import Field, SQLModel

from saki_api.models.base import UUIDMixin
from saki_api.models.rbac.role import RoleBase, RoleMetadata
from saki_api.schemas.role_permission import RolePermissionCreate, RolePermissionRead


# ============================================================================
# Role Schemas
# ============================================================================

class RoleCreate(RoleBase):
    permissions: List[RolePermissionCreate] = Field(
        default_factory=list,
        description="List of permissions"
    )


class RoleRead(RoleBase, RoleMetadata, UUIDMixin):
    permissions: List[RolePermissionRead] = []


class RoleReadMinimal(SQLModel, UUIDMixin):
    """用于在用户列表中嵌套显示的极简角色信息"""
    name: str
    display_name: Optional[str]
    color: Optional[str] = Field(default="blue", description="Role color")
    description: Optional[str] = Field(description="Role description")
    is_supremo: bool


class RoleUpdate(SQLModel):
    display_name: Optional[str] = Field(description="Role display name")
    description: Optional[str] = Field(description="Role description")
    color: Optional[str] = Field(description="Role color")
    sort_order: Optional[int] = Field(description="Role sort order")
    permissions: Optional[List[RolePermissionCreate]] = None


class RoleSetDefault(UUIDMixin):
    pass
