"""
Role and RolePermission models.

Supports:
- System roles (global) and resource roles (per-resource)
- Role inheritance through parent_id
- Dynamic permission management
- System preset roles (cannot be deleted)
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.rbac.enums import RoleType

if TYPE_CHECKING:
    pass


class RolePermission(SQLModel, table=True):
    """
    Role-Permission mapping table.
    
    Stores permissions assigned to each role.
    Permission format: resource:action:scope (e.g., "dataset:read:owned")
    """
    __tablename__ = "role_permission"
    
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique identifier"
    )
    role_id: str = Field(
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
    
    # Relationship
    role: "Role" = Relationship(back_populates="permissions")


class Role(SQLModel, table=True):
    """
    Role definition table.
    
    Supports:
    - System roles (global scope)
    - Resource roles (per-resource scope)
    - Role inheritance
    - System preset protection
    """
    __tablename__ = "role"
    
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique identifier"
    )
    
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
    parent_id: Optional[str] = Field(
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
    
    # Ordering
    sort_order: int = Field(
        default=0,
        description="Display order"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation time"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update time"
    )
    
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


# ============================================================================
# Schema Models
# ============================================================================

class RolePermissionCreate(SQLModel):
    """Schema for creating a role permission."""
    permission: str = Field(description="Permission string (resource:action:scope)")
    conditions: Optional[dict] = Field(default=None, description="Optional conditions")


class RolePermissionRead(SQLModel):
    """Schema for reading a role permission."""
    id: str
    permission: str
    conditions: Optional[dict] = None


class RoleCreate(SQLModel):
    """Schema for creating a role."""
    name: str = Field(min_length=2, max_length=50, description="Role identifier")
    display_name: str = Field(min_length=1, max_length=100, description="Display name")
    description: Optional[str] = Field(default=None, max_length=500)
    type: RoleType = Field(default=RoleType.RESOURCE)
    parent_id: Optional[str] = Field(default=None, description="Parent role ID")
    permissions: List[RolePermissionCreate] = Field(
        default_factory=list,
        description="List of permissions"
    )


class RoleRead(SQLModel):
    """Schema for reading a role."""
    id: str
    name: str
    display_name: str
    description: Optional[str] = None
    type: RoleType
    parent_id: Optional[str] = None
    is_system: bool
    is_default: bool
    sort_order: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    permissions: List[RolePermissionRead] = []


class RoleUpdate(SQLModel):
    """Schema for updating a role."""
    display_name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    parent_id: Optional[str] = None
    sort_order: Optional[int] = None
    permissions: Optional[List[RolePermissionCreate]] = None
