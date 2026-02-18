"""
Annotation System Facade

Provides a unified interface for annotation operations by combining
dataset processing and annotation sync functionality.
"""

from typing import Any, Dict, Optional

from fastapi import UploadFile
from loguru import logger

from saki_api.modules.annotation.extensions.dataset_processing.base import (
    BaseDatasetProcessor,
    UploadContext,
    ProcessResult,
    ProgressCallback,
)
from saki_api.modules.annotation.extensions.sync.base import (
    BaseAnnotationSyncHandler,
    AnnotationContext,
    SyncResult,
)
from saki_api.modules.shared.modeling.enums import DatasetType, AnnotationType


class AnnotationSystemFacade:
    """
    Unified facade for annotation system operations.

    This class combines a dataset processor and an annotation sync handler
    to provide a single interface for all annotation-related operations.

    Example:
        # Get the facade for a dataset type
        facade = AnnotationSystemFactory.create_system(DatasetType.FEDO, session)

        # Process file upload
        result = await facade.process_upload(file, context)

        # Handle annotation sync
        sync_result = facade.on_annotation_create(...)
    """

    def __init__(
            self,
            dataset_processor: BaseDatasetProcessor,
            sync_handler: BaseAnnotationSyncHandler,
    ):
        """
        Initialize the facade with processor and sync handler.

        Args:
            dataset_processor: Dataset processor for data ingestion
            sync_handler: Annotation sync handler for real-time sync
        """
        self.dataset_processor = dataset_processor
        self.sync_handler = sync_handler
        self.logger = logger.bind(component=f"{__name__}.{dataset_processor.__class__.__name__}")

    # ==================== Dataset Processing Methods ====================

    async def process_upload(
            self,
            file: UploadFile,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process an uploaded file.

        Delegates to the dataset processor.

        Args:
            file: Uploaded file
            context: Upload context
            progress_callback: Optional progress callback

        Returns:
            ProcessResult with sample information
        """
        return await self.dataset_processor.process_upload(file, context, progress_callback)

    def validate_file(self, file_path, context: UploadContext):
        """Validate if a file can be processed."""
        return self.dataset_processor.validate_file(file_path, context)

    @property
    def supported_extensions(self) -> set[str]:
        """Get supported file extensions."""
        return self.dataset_processor.supported_extensions

    # ==================== Annotation Sync Methods ====================

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
        Handle annotation creation during real-time sync.

        Delegates to the sync handler.

        Args:
            annotation_id: ID of the new annotation
            label_id: Label ID
            ann_type: Annotation type
            geometry: Geometry ProtoJSON data
            attrs: System-specific attrs data
            context: Annotation context

        Returns:
            SyncResult with any generated annotations
        """
        return self.sync_handler.on_annotation_create(
            annotation_id, label_id, ann_type, geometry, attrs, context
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
        Handle annotation update during real-time sync.

        Delegates to the sync handler.

        Args:
            annotation_id: ID of the annotation being updated
            label_id: New label ID
            ann_type: New annotation type
            geometry: New geometry data
            attrs: New attrs data
            context: Annotation context

        Returns:
            SyncResult with any generated annotations
        """
        return self.sync_handler.on_annotation_update(
            annotation_id, label_id, ann_type, geometry, attrs, context
        )

    def on_annotation_delete(
            self,
            annotation_id: str,
            attrs: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation deletion during real-time sync.

        Delegates to the sync handler.

        Args:
            annotation_id: ID of the annotation being deleted
            attrs: Attrs data from the annotation
            context: Annotation context

        Returns:
            SyncResult with any child annotations to delete
        """
        return self.sync_handler.on_annotation_delete(annotation_id, attrs, context)

    # ==================== Utility Methods ====================

    @property
    def system_type(self) -> DatasetType:
        """Get the dataset type this facade handles."""
        return self.dataset_processor.system_type
