"""
RBAC (Role-Based Access Control) schemas.

Contains schemas for Role, RolePermission, UserSystemRole, ResourceMember, and AuditLog.
"""
import uuid
from datetime import datetime
from typing import Optional, List

from sqlmodel import SQLModel, Field

# Import enums directly to avoid circular imports
from saki_api.models.rbac.enums import RoleType, ResourceType, AuditAction


# ============================================================================
# Role Permission Schemas
# ============================================================================

class RolePermissionCreate(SQLModel):
    """Schema for creating a role permission."""
    permission: str = Field(description="Permission string (resource:action:scope)")
    conditions: Optional[dict] = Field(default=None, description="Optional conditions")


class RolePermissionRead(SQLModel):
    """Schema for reading a role permission."""
    id: uuid.UUID
    permission: str
    conditions: Optional[dict] = None


# ============================================================================
# Role Schemas
# ============================================================================

class RoleCreate(SQLModel):
    """Schema for creating a role."""
    name: str = Field(min_length=2, max_length=50, description="Role identifier")
    display_name: str = Field(min_length=1, max_length=100, description="Display name")
    description: Optional[str] = Field(default=None, max_length=500)
    type: RoleType = Field(default=RoleType.RESOURCE)
    parent_id: Optional[uuid.UUID] = Field(default=None, description="Parent role ID")
    permissions: List[RolePermissionCreate] = Field(
        default_factory=list,
        description="List of permissions"
    )


class RoleRead(SQLModel):
    """Schema for reading a role."""
    id: uuid.UUID
    name: str
    display_name: str
    description: Optional[str] = None
    type: RoleType
    parent_id: Optional[uuid.UUID] = None
    is_system: bool
    is_default: bool
    is_super_admin: bool
    is_admin: bool
    sort_order: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    permissions: List[RolePermissionRead] = []


class RoleUpdate(SQLModel):
    """Schema for updating a role."""
    display_name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    parent_id: Optional[uuid.UUID] = None
    sort_order: Optional[int] = None
    permissions: Optional[List[RolePermissionCreate]] = None


# ============================================================================
# User System Role Schemas
# ============================================================================

class UserSystemRoleCreate(SQLModel):
    """Schema for assigning a system role to a user."""
    role_id: uuid.UUID = Field(description="Role ID to assign")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional expiration time"
    )


class UserSystemRoleRead(SQLModel):
    """Schema for reading a user's system role."""
    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    assigned_at: datetime
    assigned_by: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None

    # Include role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None


# ============================================================================
# Resource Member Schemas
# ============================================================================

class ResourceMemberCreate(SQLModel):
    """Schema for adding a resource member."""
    user_id: uuid.UUID = Field(description="User ID to add")
    role_id: uuid.UUID = Field(description="Role ID to assign")


class ResourceMemberRead(SQLModel):
    """Schema for reading a resource member."""
    id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    created_at: datetime
    created_by: Optional[uuid.UUID] = None
    updated_at: Optional[datetime] = None

    # User details
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None

    # Role details
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None


class ResourceMemberUpdate(SQLModel):
    """Schema for updating a resource member."""
    role_id: uuid.UUID = Field(description="New role ID")


# ============================================================================
# Audit Log Schemas
# ============================================================================

class AuditLogRead(SQLModel):
    """Schema for reading an audit log entry."""
    id: uuid.UUID
    actor_id: Optional[uuid.UUID] = None
    action: AuditAction
    target_type: str
    target_id: str
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    # Actor details (joined)
    actor_email: Optional[str] = None
