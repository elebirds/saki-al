"""
Annotation model for storing annotation data.
Annotations belong to Samples and reference Labels.

Supports:
- Multiple annotation types (rect, obb, polygon, etc.)
- Manual and auto-generated annotations
- Flexible extra data for system-specific extensions (FEDO dual-view, etc.)
"""
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from saki_api.models.base import TimestampMixin, UUIDMixin
from saki_api.models.enums import AnnotationType, AnnotationSource
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.sample import Sample
    from saki_api.models.label import Label


class AnnotationBase(SQLModel):
    """
    Base model for Annotation.
    Stores the actual labeling data for a sample.
    """
    sample_id: str = Field(foreign_key="sample.id", index=True,
                           description="ID of the sample being annotated.")
    label_id: str = Field(foreign_key="label.id", index=True,
                          description="ID of the label for this annotation.")

    # Annotation type determines how 'data' is interpreted
    type: AnnotationType = Field(default=AnnotationType.RECT, index=True,
                                 description="Geometric type of the annotation (rect, obb, polygon, etc.)")

    # Source indicates if annotation is manual or auto-generated
    source: AnnotationSource = Field(default=AnnotationSource.MANUAL, index=True,
                                     description="Source of annotation (manual, auto, imported)")

    # The actual annotation geometry data
    # For RECT: {x, y, width, height}
    # For OBB: {cx, cy, width, height, rotation}
    # For POLYGON/POLYLINE: {points: [[x1,y1], [x2,y2], ...]}
    data: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict),
                                           description="The annotation geometry data.")

    # System-specific extra data (flexible JSON for different annotation systems)
    # Examples:
    #   - FEDO: {parent_id, view: "time-energy"|"L-omegad", mapping_info, ...}
    #   - Classic: {} (empty, no extra data needed)
    #   - Future systems can add their own fields
    extra: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict),
                                            description="System-specific extra data for this annotation.")

    # User who created the annotation
    annotator_id: Optional[str] = Field(default=None,
                                        description="ID of the user or system that created the annotation.")


class Annotation(AnnotationBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Annotation.
    """
    sample: "Sample" = Relationship(back_populates="annotations")
    label: "Label" = Relationship(back_populates="annotations")


class AnnotationCreate(AnnotationBase):
    """
    Model for creating a new Annotation.
    """
    pass


class AnnotationRead(AnnotationBase, TimestampMixin, UUIDMixin):
    """
    Model for reading Annotation data.
    """
    # Include label info for convenience
    label_name: Optional[str] = None
    label_color: Optional[str] = None


class AnnotationUpdate(SQLModel):
    """
    Model for updating an Annotation.
    """
    label_id: Optional[str] = None
    type: Optional[AnnotationType] = None
    data: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


# ============================================================================
# Annotation Session Models (for real-time sync during annotation)
# ============================================================================

class AnnotationAction(SQLModel):
    """
    Single annotation action for real-time sync.
    Sent from frontend when user creates/modifies/deletes an annotation.
    """
    action: str = Field(description="Action type: 'create', 'update', 'delete'")
    annotation_id: str = Field(description="ID of the annotation")

    # For create/update actions
    label_id: Optional[str] = None
    type: Optional[AnnotationType] = None
    data: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class AnnotationSyncRequest(SQLModel):
    """
    Request for syncing annotation actions.
    """
    sample_id: str
    actions: List[AnnotationAction]


class AnnotationSyncResult(SQLModel):
    """
    Result of a single annotation sync action.
    For special systems like FEDO, includes generated linked annotations.
    """
    action: str
    annotation_id: str
    success: bool
    error: Optional[str] = None

    # Auto-generated annotations (e.g., FEDO dual-view mapping)
    generated: List[Dict[str, Any]] = Field(default=[])


class AnnotationSyncResponse(SQLModel):
    """
    Response for annotation sync request.
    """
    sample_id: str
    results: List[AnnotationSyncResult]
    # Whether the sample is ready for more annotations
    ready: bool = True


class AnnotationBatchSaveRequest(SQLModel):
    """
    Request for batch saving annotations to database.
    Called when user clicks 'Save' button.
    """
    sample_id: str
    annotations: List[AnnotationCreate]
    # Update sample status after save
    update_status: Optional[str] = None  # 'labeled', 'skipped', None


class AnnotationBatchSaveResponse(SQLModel):
    """
    Response for batch save request.
    """
    sample_id: str
    saved_count: int
    success: bool
    error: Optional[str] = None
