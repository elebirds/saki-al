# ============================================================================
# Schema Models
# ============================================================================
import uuid
from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, SQLModel


class UserCreate(SQLModel):
    """Schema for creating a user."""
    email: str = Field(max_length=255)
    password: str = Field(min_length=6)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    # Role will be assigned separately or default role will be auto-assigned


class UserRead(SQLModel):
    """Schema for reading user data."""
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    must_change_password: bool = False
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None

    # Include role information
    system_roles: List[dict] = []  # [{id, name, displayName}]

    class Config:
        from_attributes = True


class UserUpdate(SQLModel):
    """Schema for updating a user."""
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=6)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None
    must_change_password: Optional[bool] = None
    avatar_url: Optional[str] = Field(default=None, max_length=500)


class UserWithPermissions(UserRead):
    """Extended user schema with permission details."""
    permissions: List[str] = []  # List of permission strings
    is_super_admin: bool = False


# ========================================================
# User List Item
# ========================================================
class UserListItem(SQLModel):
    """Simplified user info for member selection."""
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
