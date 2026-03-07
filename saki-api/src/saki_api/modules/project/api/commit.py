"""
Commit Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import SQLModel

from saki_api.modules.shared.modeling.enums import AuthorType


class CommitBase(SQLModel):
    """
    Base commit fields shared across schemas.
    """
    project_id: uuid.UUID
    message: str
    author_type: AuthorType = AuthorType.USER
    author_id: uuid.UUID | None = None
    stats: dict[str, Any] = {}
    extra: dict[str, Any] = {}


class CommitCreate(CommitBase):
    """
    Schema for creating a commit.
    """
    parent_id: uuid.UUID | None = None


class CommitUpdate(SQLModel):
    """
    Commit is immutable - no update schema.
    Use this only for metadata updates if absolutely necessary.
    """
    message: str | None = None
    stats: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class CommitRead(CommitBase):
    """
    Schema for reading a commit.
    """
    id: uuid.UUID
    commit_hash: str
    parent_id: uuid.UUID | None
    created_at: Any
    updated_at: Any


class CommitHistoryItem(SQLModel):
    """
    Simplified commit schema for history lists.
    """
    id: uuid.UUID
    commit_hash: str
    message: str
    author_type: AuthorType
    author_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    created_at: Any
    stats: dict[str, Any] = {}


class CommitTree(SQLModel):
    """
    Commit tree structure for visualizing version history.
    """
    id: uuid.UUID
    message: str
    parent_id: uuid.UUID | None
    children: list["CommitTree"] = []


# Update forward reference
CommitTree.model_rebuild()


class CommitDiff(SQLModel):
    """
    Schema for commit diff results.
    """
    from_commit_id: uuid.UUID
    to_commit_id: uuid.UUID
    added_samples: list[uuid.UUID] = []
    removed_samples: list[uuid.UUID] = []
    modified_annotations: dict[uuid.UUID, dict] = {}  # sample_id -> {old: [], new: []}
