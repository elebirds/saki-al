"""
Schemas for Annotation Draft and Working Area payloads.
"""

import uuid
from enum import Enum
from typing import Any, List, Optional

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.enums import AnnotationType, AnnotationSource


class AnnotationDraftItem(SQLModel):
    """
    Single annotation item stored in Working/Draft payloads.
    Project and sample IDs are optional in payload and can be injected by server.
    """
    id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    sample_id: Optional[uuid.UUID] = None
    label_id: uuid.UUID
    group_id: uuid.UUID
    lineage_id: uuid.UUID
    view_role: str = "main"
    type: AnnotationType = AnnotationType.RECT
    source: AnnotationSource = AnnotationSource.MANUAL
    geometry: dict[str, Any] = Field(default_factory=dict)
    attrs: dict[str, Any] = Field(default_factory=dict)
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


class AnnotationDraftBatchOperation(str, Enum):
    CLEAR_DRAFTS = "clear_drafts"
    CONFIRM_MODEL_ANNOTATIONS = "confirm_model_annotations"
    CLEAR_UNCONFIRMED_MODEL_ANNOTATIONS = "clear_unconfirmed_model_annotations"


class AnnotationDraftBatchRequest(SQLModel):
    branch_name: str = "master"
    dataset_id: uuid.UUID
    q: Optional[str] = None
    status: str = "all"
    sort_by: str = "createdAt"
    sort_order: str = "desc"
    operation: AnnotationDraftBatchOperation
    dry_run: bool = True


class AnnotationDraftBatchResult(SQLModel):
    operation: AnnotationDraftBatchOperation
    dry_run: bool
    branch_name: str
    matched_sample_count: int
    matched_draft_count: int
    affected_draft_count: int
    affected_annotation_count: int
    updated_draft_count: int = 0
    deleted_draft_count: int = 0
    cleared_working_count: int = 0
