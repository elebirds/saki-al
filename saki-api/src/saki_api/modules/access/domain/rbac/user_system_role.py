"""
User-SystemRole association model.

Links users to system-wide roles (not resource-specific).
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import sqlalchemy as sa
from sqlmodel import Field, SQLModel, Relationship

from saki_api.modules.shared.modeling.base import UUIDMixin, TimestampMixin, AuditMixin

if TYPE_CHECKING:
    from saki_api.modules.access.domain.access.user import User
    from saki_api.modules.access.domain.rbac.role import Role


class UserSystemRoleBase(SQLModel):
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        index=True,
        description="User ID"
    )
    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        index=True,
        description="Role ID"
    )
    # Optional expiration
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When this role assignment expires (null = never)",
        sa_type=sa.DateTime(timezone=True),
    )


class UserSystemRole(UserSystemRoleBase, UUIDMixin, TimestampMixin, AuditMixin, table=True):
    __tablename__ = "user_system_role"

    user: "User" = Relationship(
        back_populates="role_assignments",
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.user_id]"}
    )
    role: "Role" = Relationship(
        back_populates="user_assignments",
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.role_id]"}
    )
