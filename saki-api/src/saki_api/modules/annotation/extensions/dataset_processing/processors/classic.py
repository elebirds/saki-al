"""
Classic dataset processor.

Handles standard image annotation (classification, detection, segmentation).

This processor:
- Supports image formats: .jpg, .png, .gif, .bmp, .webp, .tiff
- File size limit: 50MB
- Single asset workflow: Uploads one image, returns single asset_id
"""

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.extensions.dataset_processing.base import (
    BaseDatasetProcessor,
    EventType,
    ProcessingStage,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    UploadContext,
)
from saki_api.modules.annotation.extensions.dataset_processing.registry import register_processor
from saki_api.modules.shared.modeling.enums import DatasetType


@register_processor
class ClassicProcessor(BaseDatasetProcessor):
    """
    Processor for classic image annotation.

    Supports standard image formats for:
    - Image classification
    - Object detection (bounding boxes)
    - Image segmentation (polygons)

    Processing:
    1. Receives a single image file
    2. Uploads to object storage via AssetService
    3. Returns asset_ids and primary_asset_id for Sample
    """

    system_type = DatasetType.CLASSIC

    def __init__(self, session: Optional[AsyncSession] = None):
        """Initialize with database session for asset operations."""
        super().__init__(session)

    @property
    def supported_extensions(self) -> set[str]:
        return {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        is_valid, error = super().validate_file(file_path, context)
        if not is_valid:
            return is_valid, error

        # Check file size (max 50MB) if path exists
        if file_path.exists():
            max_size = 50 * 1024 * 1024
            if file_path.stat().st_size > max_size:
                return False, "File too large. Maximum size is 50MB."

        return True, ""

    async def _upload_image_asset(
            self,
            file: UploadFile,
            progress_callback: Optional[ProgressCallback] = None,
            progress: Optional[ProgressInfo] = None
    ):
        """
        Upload image file to object storage.

        Args:
            file: Uploaded file
            progress_callback: Optional progress callback
            progress: Optional progress info to update

        Returns:
            Created Asset record

        Raises:
            RuntimeError: If AssetService not initialized
        """
        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")

        if progress_callback and progress:
            progress.update(1, "Uploading to storage", ProcessingStage.CLASSIC_UPLOAD)
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        asset = await self.asset_service.upload_file(
            file,
            meta_info={"generated": False}  # Original file, not generated
        )

        return asset

    def _extract_image_metadata(
            self,
            asset_meta: Dict[str, Any],
            progress_callback: Optional[ProgressCallback] = None,
            progress: Optional[ProgressInfo] = None
    ) -> Dict[str, Any]:
        """
        Extract image metadata from asset metadata.

        Args:
            asset_meta: Asset metadata dictionary
            progress_callback: Optional progress callback
            progress: Optional progress info to update

        Returns:
            Filtered metadata dictionary
        """
        if progress_callback and progress:
            progress.update(2, "Extracting metadata", ProcessingStage.CLASSIC_METADATA)
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        if not asset_meta:
            return {}

        return {
            k: v for k, v in asset_meta.items()
            if k in ("width", "height", "format", "mode", "dpi")
        }

    def _build_process_result(
            self,
            filename: str,
            sample_id: str,
            asset_id: str,
            image_meta: Dict[str, Any]
    ) -> ProcessResult:
        """
        Build ProcessResult from uploaded asset.

        Args:
            filename: Original filename
            sample_id: Generated sample ID
            asset_id: Uploaded asset ID
            image_meta: Extracted image metadata

        Returns:
            ProcessResult with asset information
        """
        return ProcessResult(
            success=True,
            sample_id=sample_id,
            filename=filename,
            asset_ids={
                "image_main": asset_id  # Primary asset
            },
            primary_asset_id=asset_id,  # Set as primary for display
            sample_fields={
                "meta_info": {
                    "original_filename": filename,
                    **image_meta,
                }
            }
        )

    async def process_upload(
            self,
            file: UploadFile,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a classic image file.

        For classic annotation:
        1. Upload image to object storage via AssetService
        2. Extract image metadata
        3. Return ProcessResult with asset information

        Args:
            file: Uploaded file (UploadFile from FastAPI)
            context: Upload context with dataset info
            progress_callback: Optional progress callback

        Returns:
            ProcessResult with asset_ids and primary_asset_id set
        """
        filename = file.filename or "unknown"
        sample_id = self.generate_id()

        self.emit(EventType.PROCESS_START, {"filename": filename})

        # Initialize progress
        progress = None
        if progress_callback:
            progress = ProgressInfo(
                current=0, total=3, percentage=0,
                message=f"Processing image: {filename}",
                stage="classic_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            # 1. Upload file to object storage
            asset = await self._upload_image_asset(file, progress_callback, progress)

            # 2. Extract image metadata
            image_meta = self._extract_image_metadata(
                asset.meta_info,
                progress_callback,
                progress
            )

            if progress_callback and progress:
                progress.update(3, "Complete", ProcessingStage.CLASSIC_COMPLETE)
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": sample_id,
                "asset_id": str(asset.id),
            })

            # 3. Return result with asset information
            return self._build_process_result(
                filename=filename,
                sample_id=sample_id,
                asset_id=str(asset.id),
                image_meta=image_meta
            )

        except Exception as e:
            self.logger.error("处理图像失败 filename={} error={}", filename, e)
            self.emit(EventType.PROCESS_ERROR, {"filename": filename, "error": str(e)})
            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )
