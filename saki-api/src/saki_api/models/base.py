import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """
    Mixin to add created_at and updated_at timestamps to a model.
    """
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt",
                                 description="The time when the record was created.")
    updated_at: datetime = Field(default_factory=datetime.utcnow, alias="updatedAt",
                                 description="The time when the record was last updated.")

    class Config:
        populate_by_name = True


class UUIDMixin(SQLModel):
    """
    Mixin to add a UUID primary key to a model.
    """
    id: uuid.UUID = Field(default_factory=lambda: uuid.uuid4(), primary_key=True,
                          description="Unique identifier for the record.")


class AuditMixin(SQLModel):
    """
    Mixin to add audit fields (created_by, updated_by) to a model.
    
    These fields are automatically populated by SQLAlchemy event listeners
    using ContextVar to get the current user ID.
    """
    created_by: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="User ID who created the record."
    )
    updated_by: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="User ID who last updated the record."
    )


OPT_JSON = JSON().with_variant(postgresql.JSONB(), "postgresql")
