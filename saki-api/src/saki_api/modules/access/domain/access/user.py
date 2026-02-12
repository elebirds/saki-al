"""
User model.

Updated to use the new RBAC system with system roles and resource memberships.
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.access.domain.rbac import ResourceMember
    from saki_api.modules.shared.modeling import Role


class UserBase(SQLModel):
    """Base user fields."""
    email: str = Field(
        unique=True,
        index=True,
        max_length=255,
        description="User email address"
    )
    full_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Full name of the user"
    )
    is_active: bool = Field(
        default=True,
        description="Whether the user account is active"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="URL to user's avatar image"
    )


class InitedUserBase(UserBase):
    # Last login tracking
    last_login_at: Optional[datetime] = Field(
        default=None,
        description="Last login timestamp"
    )


class User(UserBase, TimestampMixin, UUIDMixin, table=True):
    """
    User database model.
    """
    __tablename__ = "user"

    must_change_password: bool = Field(default=False, description="Must change password")
    hashed_password: str = Field(description="Hashed password")

    # A. 业务快捷方式：直接拿 Role 对象 (Many-to-Many)
    # 注意：设置 overlaps 避免与一对多关系冲突
    roles: List["Role"] = Relationship(
        back_populates="users",
        sa_relationship_kwargs={
            "secondary": "user_system_role",
            "primaryjoin": "User.id == UserSystemRole.user_id",
            "secondaryjoin": "UserSystemRole.role_id == Role.id",
            "viewonly": True,  # 强烈建议设为只读，通过 assignments 维护数据
        }
    )

    # B. 管理路径：操作中间表对象 (One-to-Many)
    role_assignments: List["UserSystemRole"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "[UserSystemRole.user_id]"
        }
    )

    # Relationships - Resource memberships (per-resource permissions)
    resource_memberships: List["ResourceMember"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "foreign_keys": "[ResourceMember.user_id]",
            "cascade": "all, delete-orphan"
        }
    )
