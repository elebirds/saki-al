from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
import uuid

class TimestampMixin(SQLModel):
    """
    Mixin to add created_at and updated_at timestamps to a model.
    """
    created_at: datetime = Field(default_factory=datetime.utcnow, description="The time when the record was created.")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="The time when the record was last updated.")

class UUIDMixin(SQLModel):
    """
    Mixin to add a UUID primary key to a model.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, description="Unique identifier for the record.")
