"""
User-SystemRole association model.

Links users to system-wide roles (not resource-specific).
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.user import User
    from saki_api.models.rbac.role import Role


class UserSystemRole(SQLModel, table=True):
    """
    User-System Role association table.
    
    Associates users with system-wide roles (not resource-specific).
    System roles grant global permissions across the system.
    """
    __tablename__ = "user_system_role"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique identifier"
    )
    user_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="User ID"
    )
    role_id: str = Field(
        foreign_key="role.id",
        index=True,
        description="Role ID"
    )

    # Assignment metadata
    assigned_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the role was assigned"
    )
    assigned_by: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        description="Who assigned this role"
    )

    # Optional expiration
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When this role assignment expires (null = never)"
    )

    # Relationships
    user: "User" = Relationship(
        back_populates="system_roles",
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.user_id]"}
    )
    role: "Role" = Relationship()
    assigner: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[UserSystemRole.assigned_by]"}
    )


# ============================================================================
# Schema Models
# ============================================================================

class UserSystemRoleCreate(SQLModel):
    """Schema for assigning a system role to a user."""
    role_id: str = Field(description="Role ID to assign")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional expiration time"
    )


class UserSystemRoleRead(SQLModel):
    """Schema for reading a user's system role."""
    id: str
    user_id: str
    role_id: str
    assigned_at: datetime
    assigned_by: Optional[str] = None
    expires_at: Optional[datetime] = None

    # Include role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
