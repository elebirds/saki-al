"""
AnnotationDraft model for staging annotations (L2 Working Directory).
"""

import uuid
from typing import Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON


class AnnotationDraftBase(SQLModel):
    """
    Base model for AnnotationDraft.
    Stores draft annotation payloads for a user and sample.
    """

    project_id: uuid.UUID = Field(
        foreign_key="project.id",
        index=True,
        description="ID of the project this draft belongs to.",
    )
    sample_id: uuid.UUID = Field(
        foreign_key="sample.id",
        index=True,
        description="ID of the sample this draft belongs to.",
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        index=True,
        description="ID of the user who owns this draft.",
    )
    branch_name: str = Field(
        default="master",
        max_length=100,
        index=True,
        description="Target branch name for this draft.",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="Draft annotation payload (list of annotations and metadata).",
    )


class AnnotationDraft(AnnotationDraftBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for annotation drafts (staging area).
    """
    __tablename__ = "annotation_draft"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "sample_id", "user_id", "branch_name",
            name="uq_annotation_draft",
        ),
    )
