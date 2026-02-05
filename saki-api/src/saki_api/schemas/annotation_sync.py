"""
Schemas for annotation real-time sync (FEDO dual-view mapping).
"""

import uuid
from typing import Any, Dict, List, Literal, Optional

from sqlmodel import Field, SQLModel

from saki_api.models.enums import AnnotationType


class AnnotationSyncRequest(SQLModel):
    """
    Request payload for annotation sync.
    """
    action: Literal["create", "update", "delete"]
    annotation_id: str
    label_id: Optional[uuid.UUID] = None
    type: Optional[AnnotationType] = None
    data: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class AnnotationSyncResponse(SQLModel):
    """
    Response payload for annotation sync.
    """
    success: bool
    annotation_id: str
    action: str
    error: Optional[str] = None
    generated: List[Dict[str, Any]] = Field(default_factory=list)
