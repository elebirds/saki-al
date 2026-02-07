import uuid
from typing import Optional, List

from sqlmodel import SQLModel, Field

from saki_api.models.base import UUIDMixin, TimestampMixin
from saki_api.models.user import UserBase, InitedUserBase
from saki_api.schemas import RoleReadMinimal


# ========================================================
# User Schema
# ========================================================

class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserRead(InitedUserBase, UUIDMixin, TimestampMixin):
    roles: List[RoleReadMinimal] = []


class UserUpdate(UserCreate):
    pass


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
