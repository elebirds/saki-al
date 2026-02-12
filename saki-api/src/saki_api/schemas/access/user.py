import uuid
from typing import Optional, List

from sqlmodel import SQLModel, Field

from saki_api.models.base import UUIDMixin, TimestampMixin
from saki_api.models.access.user import UserBase, InitedUserBase
from saki_api.schemas import RoleReadMinimal


# ========================================================
# User Schema
# ========================================================

class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserRead(InitedUserBase, UUIDMixin, TimestampMixin):
    roles: List[RoleReadMinimal] = []


class UserUpdate(SQLModel):
    """Partial user update payload."""
    email: Optional[str] = Field(default=None, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    password: Optional[str] = Field(default=None, min_length=6)


class UserReadWithPermissions(UserRead):
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
