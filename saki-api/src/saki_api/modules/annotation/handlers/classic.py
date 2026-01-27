"""
Classic annotation system handler.
Handles standard image annotation (classification, detection, segmentation).

This is the default handler for most annotation tasks. It provides:
- Image file upload and processing
- Standard annotation sync (pass-through, no special processing)
"""

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from saki_api.modules.annotation.base import (
    AnnotationSystemHandler,
    EventType,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    UploadContext,
)
from saki_api.modules.annotation.registry import register_handler
from saki_api.models.enums import AnnotationSystemType


@register_handler
class ClassicHandler(AnnotationSystemHandler):
    """
    Handler for classic image annotation system.
    
    Supports standard image formats for:
    - Image classification
    - Object detection (bounding boxes)
    - Image segmentation (polygons)
    
    Annotation sync uses default pass-through - no special processing needed.
    """

    system_type = AnnotationSystemType.CLASSIC

    @property
    def supported_extensions(self) -> set[str]:
        return {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        is_valid, error = super().validate_file(file_path, context)
        if not is_valid:
            return is_valid, error

        # Check file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if file_path.stat().st_size > max_size:
            return False, "File too large. Maximum size is 50MB."

        return True, ""

    def process_upload(
            self,
            file_path: Path,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a classic image file.
        
        For classic annotation, processing is minimal:
        - Generate sample ID
        - Copy file to storage
        - Extract basic image metadata
        """
        filename = file_path.name
        sample_id = self.generate_id()

        self.emit(EventType.PROCESS_START, {"filename": filename})

        if progress_callback:
            progress = ProgressInfo(
                current=0, total=2, percentage=0,
                message=f"Processing image: {filename}",
                stage="classic_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            # Get image dimensions (optional, for metadata)
            image_meta = self._get_image_metadata(file_path)

            if progress_callback:
                progress.update(1, "Preparing image", "classic_prepare")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            # Prepare storage path
            output_dir = context.upload_dir / sample_id
            output_dir.mkdir(parents=True, exist_ok=True)

            # Copy image to storage
            stored_path = output_dir / filename
            shutil.copy2(file_path, stored_path)

            if progress_callback:
                progress.update(2, "Complete", "classic_complete")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": sample_id,
            })

            # Build static URL
            static_url = f"/static/{context.dataset_id}/{sample_id}/{filename}"

            return ProcessResult(
                success=True,
                sample_id=sample_id,
                filename=filename,
                sample_fields={
                    'url': static_url,
                    'meta_data': {
                        'original_filename': filename,
                        **image_meta,
                    },
                },
            )

        except Exception as e:
            self.logger.error(f"Error processing image {filename}: {e}")
            self.emit(EventType.PROCESS_ERROR, {"filename": filename, "error": str(e)})
            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )

    def _get_image_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Extract basic image metadata."""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return {
                    'width': img.width,
                    'height': img.height,
                    'format': img.format,
                    'mode': img.mode,
                }
        except Exception:
            return {}

    # Annotation sync methods use default pass-through from base class
    # No special processing needed for classic annotation
