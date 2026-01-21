"""
User-SystemRole association model.

Links users to system-wide roles (not resource-specific).
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.user import User
    from saki_api.models.rbac.role import Role


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

    # Assignment metadata
    assigned_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the role was assigned"
    )
    assigned_by: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="user.id",
        description="Who assigned this role"
    )

    # Optional expiration
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When this role assignment expires (null = never)"
    )


class UserSystemRole(UserSystemRoleBase, UUIDMixin, table=True):
    """
    User-System Role association table.
    
    Associates users with system-wide roles (not resource-specific).
    System roles grant global permissions across the system.
    """
    __tablename__ = "user_system_role"

    # Relationships
    user: "User" = Relationship(
        back_populates="system_roles",
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.user_id]"}
    )
    role: "Role" = Relationship()
    assigner: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.assigned_by]"}
    )
