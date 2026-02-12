"""
Label Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import SQLModel


class LabelBase(SQLModel):
    """
    Base label fields shared across schemas.
    """
    name: str
    color: str = "#1890ff"
    description: str | None = None
    sort_order: int = 0
    shortcut: str | None = None


class LabelCreate(LabelBase):
    """
    Schema for creating a label.
    """
    project_id: uuid.UUID  # Project to add the label to


class LabelUpdate(SQLModel):
    """
    Schema for updating a label.
    """
    name: str | None = None
    color: str | None = None
    description: str | None = None
    sort_order: int | None = None
    shortcut: str | None = None


class LabelRead(LabelBase):
    """
    Schema for reading a label.
    """
    id: uuid.UUID
    project_id: uuid.UUID
    created_at: Any
    updated_at: Any
