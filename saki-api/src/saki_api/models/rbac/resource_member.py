"""
ResourceMember model.

A generic table for associating users with resources (datasets, projects, etc.)
and assigning resource-specific roles.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, AuditMixin
from saki_api.models.rbac.enums import ResourceType

if TYPE_CHECKING:
    from saki_api.models.user import User
    from saki_api.models.rbac.role import Role


class ResourceMemberBase(SQLModel):
    # Resource identification
    resource_type: ResourceType = Field(
        index=True,
        description="Type of resource (dataset, project, etc.)"
    )
    resource_id: uuid.UUID = Field(
        index=True,
        description="ID of the resource"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        index=True,
        description="User ID"
    )
    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        description="Resource role ID"
    )


class ResourceMember(ResourceMemberBase, UUIDMixin, TimestampMixin, AuditMixin, table=True):
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

    # Relationships
    user: "User" = Relationship(
        back_populates="resource_memberships",
        sa_relationship_kwargs={"foreign_keys": "[ResourceMember.user_id]"}
    )
    role: "Role" = Relationship()
