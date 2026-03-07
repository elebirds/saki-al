"""
No-op annotation sync handler.

Used for datasets that don't require special sync processing (e.g., Classic).
All methods return success with no generated annotations.
"""

from typing import Any, Dict, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.extensions.sync.base import (
    BaseAnnotationSyncHandler,
    AnnotationContext,
    SyncResult,
)
from saki_api.modules.annotation.extensions.sync.registry import register_sync_handler
from saki_api.modules.shared.modeling.enums import DatasetType, AnnotationType


@register_sync_handler
class NoOpSyncHandler(BaseAnnotationSyncHandler):
    """
    No-op sync handler for datasets without special sync requirements.

    Used by Classic and other single-view datasets where annotations
    don't need to be mapped or synchronized across views.
    """

    system_type = DatasetType.CLASSIC

    def __init__(self, session: Optional[AsyncSession] = None):
        """Initialize with database session."""
        super().__init__(session)

    def on_annotation_create(
            self,
            annotation_id: str,
            label_id: str,
            ann_type: AnnotationType,
            geometry: Dict[str, Any],
            attrs: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation creation - no-op pass-through.

        Returns:
            SyncResult with success=True and no generated annotations
        """
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="create",
            generated=[],
        )

    def on_annotation_update(
            self,
            annotation_id: str,
            label_id: Optional[str],
            ann_type: Optional[AnnotationType],
            geometry: Optional[Dict[str, Any]],
            attrs: Optional[Dict[str, Any]],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation update - no-op pass-through.

        Returns:
            SyncResult with success=True and no generated annotations
        """
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="update",
            generated=[],
        )

    def on_annotation_delete(
            self,
            annotation_id: str,
            attrs: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation deletion - no-op pass-through.

        Returns:
            SyncResult with success=True and no generated annotations
        """
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="delete",
            generated=[],
        )
