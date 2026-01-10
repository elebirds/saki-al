"""
ResourceMember model.

A generic table for associating users with resources (datasets, projects, etc.)
and assigning resource-specific roles.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.rbac.enums import ResourceType

if TYPE_CHECKING:
    from saki_api.models.user import User
    from saki_api.models.rbac.role import Role


class ResourceMember(SQLModel, table=True):
    """
    Resource Member table.
    
    Generic table for associating users with resources and assigning
    resource-specific roles. Supports multiple resource types.
    """
    __tablename__ = "resource_member"
    __table_args__ = (
        UniqueConstraint(
            'resource_type', 'resource_id', 'user_id',
            name='uq_resource_member'
        ),
    )

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique identifier"
    )

    # Resource identification
    resource_type: ResourceType = Field(
        index=True,
        description="Type of resource (dataset, project, etc.)"
    )
    resource_id: str = Field(
        index=True,
        description="ID of the resource"
    )

    # User
    user_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="User ID"
    )

    # Role
    role_id: str = Field(
        foreign_key="role.id",
        description="Resource role ID"
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the member was added"
    )
    created_by: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        description="Who added this member"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update time"
    )

    # Relationships
    user: "User" = Relationship(
        back_populates="resource_memberships",
        sa_relationship_kwargs={"foreign_keys": "[ResourceMember.user_id]"}
    )
    role: "Role" = Relationship()
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ResourceMember.created_by]"}
    )


# ============================================================================
# Schema Models
# ============================================================================

class ResourceMemberCreate(SQLModel):
    """Schema for adding a resource member."""
    user_id: str = Field(description="User ID to add")
    role_id: str = Field(description="Role ID to assign")


class ResourceMemberRead(SQLModel):
    """Schema for reading a resource member."""
    id: str
    resource_type: ResourceType
    resource_id: str
    user_id: str
    role_id: str
    created_at: datetime
    created_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    # User details
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None

    # Role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None


class ResourceMemberUpdate(SQLModel):
    """Schema for updating a resource member."""
    role_id: str = Field(description="New role ID")
