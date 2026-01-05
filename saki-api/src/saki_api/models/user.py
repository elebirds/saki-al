from typing import Optional, TYPE_CHECKING

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.permission import GlobalRole
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.permission import DatasetMember


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True, description="User email address")
    is_active: bool = Field(default=True, description="Whether the user account is active")
    full_name: Optional[str] = Field(default=None, description="Full name of the user")
    global_role: GlobalRole = Field(
        default=GlobalRole.VIEWER,
        description="Global role of the user"
    )
    must_change_password: bool = Field(
        default=False,
        description="Whether the user must change password on next login"
    )


class User(UserBase, TimestampMixin, UUIDMixin, table=True):
    hashed_password: str = Field(description="Hashed password")

    # Relationships
    dataset_memberships: list["DatasetMember"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "foreign_keys": "[DatasetMember.user_id]"
        }
    )


class UserCreate(UserBase):
    password: str


class UserRead(UserBase, TimestampMixin, UUIDMixin):
    pass


class UserUpdate(SQLModel):
    email: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    global_role: Optional[GlobalRole] = None
    full_name: Optional[str] = None
    must_change_password: Optional[bool] = None
