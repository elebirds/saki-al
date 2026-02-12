"""
Annotation Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import SQLModel

from saki_api.modules.shared.modeling.enums import AnnotationType, AnnotationSource


class AnnotationBase(SQLModel):
    """
    Base annotation fields shared across schemas.
    """
    sample_id: uuid.UUID
    label_id: uuid.UUID
    project_id: uuid.UUID
    group_id: uuid.UUID
    lineage_id: uuid.UUID
    view_role: str = "main"
    type: AnnotationType = AnnotationType.RECT
    source: AnnotationSource = AnnotationSource.MANUAL
    data: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    confidence: float = 1.0
    annotator_id: uuid.UUID | None = None


class AnnotationCreate(AnnotationBase):
    """
    Schema for creating an annotation.

    For modifications, include parent_id to reference the annotation being modified.
    """
    parent_id: uuid.UUID | None = None


class AnnotationRead(AnnotationBase):
    """
    Schema for reading an annotation.
    """
    id: uuid.UUID
    parent_id: uuid.UUID | None
    created_at: Any
    updated_at: Any


class AnnotationUpdate(SQLModel):
    """
    Annotation is immutable - use AnnotationCreate with parent_id for modifications.

    This schema is only for metadata updates if absolutely necessary.
    """
    # No updateable fields - annotations are immutable
    # Use AnnotationCreate with parent_id instead
    pass


class AnnotationHistoryItem(SQLModel):
    """
    Schema for annotation history items.
    """
    id: uuid.UUID
    parent_id: uuid.UUID | None
    type: AnnotationType
    source: AnnotationSource
    confidence: float
    created_at: Any
    data: dict[str, Any] = {}


class AnnotationBatchCreate(SQLModel):
    """
    Schema for batch creating annotations.

    This is typically used with commit creation in the save workflow.
    """
    project_id: uuid.UUID
    branch_name: str = "master"
    commit_message: str
    annotations: list[AnnotationCreate]
