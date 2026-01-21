"""
User model.

Updated to use the new RBAC system with system roles and resource memberships.
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.rbac import UserSystemRole, ResourceMember


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
    must_change_password: bool = Field(
        default=False,
        description="Whether the user must change password on next login"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="URL to user's avatar image"
    )


class User(UserBase, TimestampMixin, UUIDMixin, table=True):
    """
    User database model.
    
    Roles are managed through:
    - system_roles: System-wide roles (UserSystemRole)
    - resource_memberships: Resource-specific roles (ResourceMember)
    """
    __tablename__ = "user"

    hashed_password: str = Field(description="Hashed password")

    # Last login tracking
    last_login_at: Optional[datetime] = Field(
        default=None,
        description="Last login timestamp"
    )

    # Relationships - System roles (global permissions)
    system_roles: List["UserSystemRole"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "foreign_keys": "[UserSystemRole.user_id]",
            "cascade": "all, delete-orphan"
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
