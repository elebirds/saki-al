"""
Role and RolePermission models.

Supports:
- System roles (global) and resource roles (per-resource)
- Role inheritance through parent_id
- Dynamic permission management
- System preset roles (cannot be deleted)
"""
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship
from saki_api.models.base import UUIDMixin, TimestampMixin
from saki_api.models.rbac.enums import RoleType
from saki_api.models.rbac.role_permission import RolePermission


if TYPE_CHECKING:
    from saki_api.models import User, UserSystemRole


class RoleCanModifyBase(SQLModel):
    display_name: str = Field(
        max_length=100,
        description="Human-readable display name"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Role description"
    )
    # Ordering
    sort_order: int = Field(
        default=0,
        description="Display order"
    )

class RoleBase(RoleCanModifyBase):
    # Basic info
    name: str = Field(
        unique=True,
        index=True,
        max_length=50,
        description="Role identifier (unique, lowercase with underscores)"
    )
    # Role type
    type: RoleType = Field(
        default=RoleType.RESOURCE,
        description="Role type: system (global) or resource (per-resource)"
    )

class RoleMetadata(SQLModel):
    # System protection
    is_system: bool = Field(
        default=False,
        description="Whether this is a system preset role (cannot be deleted)"
    )
    is_default: bool = Field(
        default=False,
        description="Whether this is the default role for new users"
    )
    is_super_admin: bool = Field(
        default=False,
        description="Whether this is the super administrator role (cannot be assigned/revoked/deleted except by super admin)"
    )
    is_admin: bool = Field(
        default=False,
        description="Whether this is the administrator role (can only be assigned/revoked by super admin)"
    )


class Role(RoleBase, RoleMetadata, UUIDMixin, TimestampMixin, table=True):
    """
    Role definition table.
    
    Supports:
    - System roles (global scope)
    - Resource roles (per-resource scope)
    - Role inheritance
    - System preset protection
    """
    __tablename__ = "role"

    # Relationships
    permissions: List["RolePermission"] = Relationship(
        back_populates="role",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    # A. 快捷方式：获取该角色下的所有用户
    users: List["User"] = Relationship(
        back_populates="roles",
        sa_relationship_kwargs={
            "secondary": "user_system_role",
            "primaryjoin": "Role.id == UserSystemRole.role_id",
            "secondaryjoin": "UserSystemRole.user_id == User.id",
            "viewonly": True,
        }
    )

    # B. 镜像路径：供中间表反向引用
    user_assignments: List["UserSystemRole"] = Relationship(
        back_populates="role",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "[UserSystemRole.role_id]"
        }
    )
