"""
Schemas for annotation full snapshot sync.
"""

import uuid
from typing import Any, Dict, List, Literal, Optional

from sqlmodel import Field, SQLModel

from saki_api.schemas.annotation_draft import AnnotationDraftItem, AnnotationDraftPayload


class AnnotationSyncAction(SQLModel):
    """
    Single sync action for incremental updates.
    """
    type: Literal["add", "update", "delete"]
    group_id: uuid.UUID
    data: Optional[AnnotationDraftItem] = None


class AnnotationSyncRequest(SQLModel):
    """
    Request payload for annotation full snapshot sync.
    """
    base_commit_id: Optional[uuid.UUID] = None
    last_seq_id: int = 0
    branch_name: str = "master"
    actions: List[AnnotationSyncAction] = Field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


class AnnotationSyncResponse(SQLModel):
    """
    Response payload for annotation sync.
    """
    status: Literal["success", "conflict"]
    current_seq_id: int
    base_commit_id: Optional[uuid.UUID] = None
    payload: AnnotationDraftPayload
