import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from saki_api.models import Role

class RolePermissionBase(SQLModel):
    permission: str = Field(max_length=100,description="Permission string (resource:action:scope)")


class RolePermission(RolePermissionBase, UUIDMixin, TimestampMixin, table=True):
    """
    Role-Permission mapping table.

    Stores permissions assigned to each role.
    Permission format: resource:action:scope (e.g., "dataset:read:owned")
    """
    __tablename__ = "role_permission"

    # Relationship
    role_id: uuid.UUID = Field(foreign_key="role.id", index=True, description="Role ID")
    role: "Role" = Relationship(back_populates="permissions")