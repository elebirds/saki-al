"""
Branch Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import SQLModel


class BranchBase(SQLModel):
    """
    Base branch fields shared across schemas.
    """
    name: str
    project_id: uuid.UUID
    head_commit_id: uuid.UUID
    description: str | None = None
    is_protected: bool = False


class BranchCreate(BranchBase):
    """
    Schema for creating a branch.
    """
    pass


class BranchUpdate(SQLModel):
    """
    Schema for updating a branch (only metadata).
    Note: Use switch_to_commit to change head_commit_id.
    """
    name: str | None = None
    description: str | None = None
    is_protected: bool | None = None


class BranchRead(BranchBase):
    """
    Schema for reading a branch.
    """
    id: uuid.UUID
    created_at: Any
    updated_at: Any


class BranchSwitch(SQLModel):
    """
    Schema for switching a branch to a different commit.
    """
    target_commit_id: uuid.UUID


class BranchReadMinimal(SQLModel):
    """
    Minimal branch schema for dropdowns/selection.
    """
    id: uuid.UUID
    name: str
    head_commit_id: uuid.UUID
    is_protected: bool
