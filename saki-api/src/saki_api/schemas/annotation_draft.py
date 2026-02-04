"""
Schemas for Annotation Draft and Working Area payloads.
"""

import uuid
from typing import Any, List, Optional

from sqlmodel import Field, SQLModel

from saki_api.models.enums import AnnotationType, AnnotationSource


class AnnotationDraftItem(SQLModel):
    """
    Single annotation item stored in Working/Draft payloads.
    Project and sample IDs are optional in payload and can be injected by server.
    """
    project_id: Optional[uuid.UUID] = None
    sample_id: Optional[uuid.UUID] = None
    label_id: uuid.UUID
    sync_id: uuid.UUID
    view_role: str = "main"
    type: AnnotationType = AnnotationType.RECT
    source: AnnotationSource = AnnotationSource.MANUAL
    data: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    annotator_id: Optional[uuid.UUID] = None
    parent_id: Optional[uuid.UUID] = None


class AnnotationDraftPayload(SQLModel):
    """
    Draft payload with annotation items and optional metadata.
    """
    annotations: List[AnnotationDraftItem]
    meta: dict[str, Any] = Field(default_factory=dict)


class AnnotationDraftUpsert(AnnotationDraftPayload):
    """
    Upsert draft payload.
    """
    branch_name: str = "master"


class AnnotationWorkingUpsert(AnnotationDraftPayload):
    """
    Upsert working payload into Redis.
    """
    branch_name: str = "master"


class AnnotationDraftRead(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    sample_id: uuid.UUID
    user_id: uuid.UUID
    branch_name: str
    payload: dict[str, Any]
    created_at: Any
    updated_at: Any


class AnnotationDraftCommitRequest(SQLModel):
    """
    Request to commit drafts into a new commit.
    """
    branch_name: str = "master"
    commit_message: str
    sample_ids: Optional[List[uuid.UUID]] = None
