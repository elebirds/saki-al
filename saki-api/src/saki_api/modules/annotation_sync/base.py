"""
Base class for annotation sync handlers.

Provides a unified interface for real-time annotation synchronization.
Each handler handles a specific dataset type (CLASSIC, FEDO, etc.)

This module is responsible for:
- Real-time annotation sync during annotation session
- Handling create/update/delete events
- Generating linked annotations (e.g., FEDO dual-view mapping)
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from saki_api.models.enums import DatasetType, AnnotationType

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AnnotationContext:
    """Context for annotation operations."""
    sample_id: str
    dataset_id: str
    project_id: Optional[str] = None
    sample_meta: Dict[str, Any] = field(default_factory=dict)
    annotator_id: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a single annotation sync action."""
    success: bool
    annotation_id: str
    action: str  # 'create', 'update', 'delete'
    error: Optional[str] = None
    # Auto-generated annotations (e.g., FEDO dual-view mapping)
    generated: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# Base Sync Handler Class
# ============================================================================

class BaseAnnotationSyncHandler(ABC):
    """
    Abstract base class for annotation sync handlers.

    Each dataset type (CLASSIC, FEDO, etc.) implements this interface
    to handle real-time annotation sync:

    1. Annotation Sync (real-time, during annotation session):
       - on_annotation_create() - Handle new annotation
       - on_annotation_update() - Handle annotation modification
       - on_annotation_delete() - Handle annotation removal

    Example:
        @register_sync_handler
        class DualViewSyncHandler(BaseAnnotationSyncHandler):
            system_type = DatasetType.FEDO

            def on_annotation_create(self, ...):
                # Generate dual-view mapped annotation
                return SyncResult(success=True, generated=[...])
    """

    # Class attribute: which dataset type this handler supports
    system_type: DatasetType

    def __init__(self, session: Optional["AsyncSession"] = None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.session = session

        # Initialize services if session is provided
        if session:
            from saki_api.services.asset import AssetService
            self.asset_service = AssetService(session)

    # ==================== Annotation Sync (Real-time) ====================

    @abstractmethod
    def on_annotation_create(
            self,
            annotation_id: str,
            label_id: str,
            ann_type: AnnotationType,
            data: Dict[str, Any],
            extra: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation creation during real-time sync.

        Override in subclasses for special processing (e.g., FEDO mapping).
        Default implementation: pass-through with no extra processing.

        Args:
            annotation_id: ID of the new annotation
            label_id: Label ID
            ann_type: Annotation type (rect, obb, polygon, etc.)
            data: Geometry data
            extra: System-specific extra data
            context: Annotation context

        Returns:
            SyncResult, with 'generated' list for auto-created annotations
        """
        pass

    @abstractmethod
    def on_annotation_update(
            self,
            annotation_id: str,
            label_id: Optional[str],
            ann_type: Optional[AnnotationType],
            data: Optional[Dict[str, Any]],
            extra: Optional[Dict[str, Any]],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation update during real-time sync.

        Override in subclasses for special processing.
        Default implementation: pass-through.

        Args:
            annotation_id: ID of the annotation being updated
            label_id: New label ID (None if not changed)
            ann_type: New annotation type (None if not changed)
            data: New geometry data (None if not changed)
            extra: New extra data (None if not changed)
            context: Annotation context

        Returns:
            SyncResult with generated annotations if any
        """
        pass

    @abstractmethod
    def on_annotation_delete(
            self,
            annotation_id: str,
            extra: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation deletion during real-time sync.

        Override in subclasses for special processing.

        Args:
            annotation_id: ID of the annotation being deleted
            extra: Extra data from the annotation
            context: Annotation context

        Returns:
            SyncResult. For linked annotations (FEDO), include child IDs to delete
            in the 'generated' field with action='delete'.
        """
        pass

    # ==================== Utilities ====================

    def generate_id(self) -> str:
        """Generate a unique annotation ID."""
        return str(uuid.uuid4())
