"""
Classic annotation system handler.
Handles standard image annotation (classification, detection, segmentation).
"""

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from saki_api.annotation_systems.base import (
    AnnotationSystemHandler,
    EventType,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    UploadContext,
)
from saki_api.annotation_systems.registry import register_handler
from saki_api.models.enums import AnnotationSystemType


@register_handler
class ClassicHandler(AnnotationSystemHandler):
    """
    Handler for classic image annotation system.
    
    Supports standard image formats for:
    - Image classification
    - Object detection
    - Image segmentation
    """

    system_type = AnnotationSystemType.CLASSIC

    @property
    def support_extensions(self) -> set[str]:
        return {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        state, reason = super().validate_file(file_path, context)
        if not state:
            return state, reason

        # Check file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if file_path.stat().st_size > max_size:
            return False, f"File too large. Maximum size is 50MB."

        return True, ""

    def process_upload(
            self,
            file_path: Path,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a classic image file.
        
        For classic annotation, processing is minimal - just validate
        the image and prepare metadata.
        
        Args:
            file_path: Path to the uploaded image file
            context: Upload context with project configuration
            progress_callback: Optional callback for progress updates
            
        Returns:
            ProcessResult with processing status and sample data
        """
        filename = file_path.name
        sample_id = str(uuid.uuid4())

        # Emit processing start event
        self.emit(EventType.PROCESS_START, {"filename": filename})

        if progress_callback:
            progress = ProgressInfo(
                current=0, total=2, percentage=0,
                message=f"Processing image: {filename}",
                stage="classic_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            # Validate the file
            is_valid, error_msg = self.validate_file(file_path, context)
            if not is_valid:
                raise ValueError(error_msg)

            if progress_callback:
                progress.update(1, "Extracting metadata", "classic_metadata")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            # Extract basic image metadata
            metadata = self._extract_image_metadata(file_path)

            # Generate URL for serving the image
            url = f"/static/{context.project_id}/{filename}"

            if progress_callback:
                progress.update(2, "Processing complete", "classic_complete")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            # Emit completion event
            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": sample_id,
            })

            return ProcessResult(
                success=True,
                sample_id=sample_id,
                filename=filename,
                sample_data={
                    'url': url,
                },
                metadata=metadata,
            )

        except Exception as e:
            self.logger.error(f"Error processing image {filename}: {e}")
            self.emit(EventType.PROCESS_ERROR, {
                "filename": filename,
                "error": str(e),
            })

            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )

    def get_sample_fields(self, result: ProcessResult) -> Dict[str, Any]:
        """
        Get fields to set on the Sample model from processing result.
        
        Returns fields specific to classic image samples:
        - url
        - meta_data
        """
        if not result.success:
            return {}

        return {
            'url': result.sample_data.get('url'),
            'meta_data': result.metadata,
        }

    def _extract_image_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from an image file.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Dictionary with image metadata
        """
        metadata: Dict[str, Any] = {
            'file_size': file_path.stat().st_size,
            'extension': file_path.suffix.lower(),
        }

        # Try to get image dimensions using PIL if available
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                metadata['width'] = img.width
                metadata['height'] = img.height
                metadata['mode'] = img.mode
                metadata['format'] = img.format
        except ImportError:
            self.logger.debug("PIL not available, skipping image dimension extraction")
        except Exception as e:
            self.logger.warning(f"Could not extract image metadata: {e}")

        return metadata
