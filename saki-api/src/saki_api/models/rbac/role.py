"""
Role and RolePermission models.

Supports:
- System roles (global) and resource roles (per-resource)
- Role inheritance through parent_id
- Dynamic permission management
- System preset roles (cannot be deleted)
"""
import uuid
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin
from saki_api.models.rbac.enums import RoleType

if TYPE_CHECKING:
    pass


class RolePermissionBase(SQLModel):
    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        index=True,
        description="Role ID"
    )
    permission: str = Field(
        max_length=100,
        description="Permission string (resource:action:scope)"
    )
    conditions: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Optional conditions for ABAC-style constraints"
    )


class RolePermission(RolePermissionBase, UUIDMixin, TimestampMixin, table=True):
    """
    Role-Permission mapping table.
    
    Stores permissions assigned to each role.
    Permission format: resource:action:scope (e.g., "dataset:read:owned")
    """
    __tablename__ = "role_permission"

    # Relationship
    role: "Role" = Relationship(back_populates="permissions")


class RoleBase(SQLModel):
    # Basic info
    name: str = Field(
        unique=True,
        index=True,
        max_length=50,
        description="Role identifier (unique, lowercase with underscores)"
    )
    display_name: str = Field(
        max_length=100,
        description="Human-readable display name"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Role description"
    )

    # Role type
    type: RoleType = Field(
        default=RoleType.RESOURCE,
        description="Role type: system (global) or resource (per-resource)"
    )

    # Inheritance
    parent_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="role.id",
        description="Parent role ID for inheritance"
    )

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

    # Ordering
    sort_order: int = Field(
        default=0,
        description="Display order"
    )


class Role(RoleBase, UUIDMixin, TimestampMixin, table=True):
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
    parent: Optional["Role"] = Relationship(
        sa_relationship_kwargs={
            "remote_side": "Role.id",
            "foreign_keys": "[Role.parent_id]"
        }
    )
