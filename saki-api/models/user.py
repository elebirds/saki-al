from typing import Optional
from sqlmodel import Field, SQLModel
from models.base import TimestampMixin, UUIDMixin

class UserBase(SQLModel):
    email: str = Field(unique=True, index=True, description="User email address")
    is_active: bool = Field(default=True, description="Whether the user account is active")
    is_superuser: bool = Field(default=False, description="Whether the user has superuser privileges")
    full_name: Optional[str] = Field(default=None, description="Full name of the user")

class User(UserBase, TimestampMixin, UUIDMixin, table=True):
    hashed_password: str = Field(description="Hashed password")

class UserCreate(UserBase):
    password: str

class UserRead(UserBase, TimestampMixin, UUIDMixin):
    pass

class UserUpdate(SQLModel):
    email: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    full_name: Optional[str] = None
