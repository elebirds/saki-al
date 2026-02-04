"""
FEDO dataset processor.

Handles satellite FEDO (electron flux) data processing with dual-view visualization.

This processor:
- Supports .txt files only
- Multi-asset workflow: Creates 5+ assets per upload
- Dual-view generation: Time-Energy <-> L-Omegad
- Generates lookup tables for coordinate mapping
"""

import io
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import DatasetType
from saki_api.modules.dataset_processing.base import (
    BaseDatasetProcessor,
    EventType,
    ProcessingStage,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    UploadContext,
)
from saki_api.modules.dataset_processing.registry import register_processor
# FEDO data processing utilities
from saki_api.modules.data_formats.fedo.processor import FedoProcessor, FedoData
from saki_api.modules.data_formats.fedo.config import FedoConfig, get_fedo_config


@register_processor
class FedoDatasetProcessor(BaseDatasetProcessor):
    """
    Processor for FEDO satellite data.

    FEDO uses dual-view visualization:
    - Time-Energy view: Energy flux vs time
    - L-Omegad view: L-shell vs drift frequency

    Processing:
    1. Parse raw text file
    2. Calculate physics (L-shell, drift frequency)
    3. Generate visualization images for both views
    4. Generate lookup tables for coordinate mapping
    5. Upload all generated assets
    6. Return ProcessResult with asset_ids mapping

    Asset Management:
    - Raw text file is stored as asset (role: raw_text)
    - Generated visualization images are stored as assets (roles: time_energy_image, l_omegad_image)
    - Lookup table and data files are stored as assets (roles: lookup_table, data_npz)
    - Primary asset is time_energy_image for frontend display
    """

    system_type = DatasetType.FEDO

    def __init__(self, session: Optional[AsyncSession] = None):
        """Initialize with database session for asset operations."""
        super().__init__(session)
        self._processors: Dict[str, FedoProcessor] = {}

    @property
    def supported_extensions(self) -> set[str]:
        return {'.txt'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        is_valid, error = super().validate_file(file_path, context)
        if not is_valid:
            return is_valid, error

        fedo_config = self._get_fedo_config(context)

        # Check FEDO file format (disk-based only)
        if file_path.exists():
            try:
                max_size = fedo_config.max_file_size_mb * 1024 * 1024
                if file_path.stat().st_size > max_size:
                    return False, f"File too large. Maximum size is {fedo_config.max_file_size_mb}MB."

                with open(file_path, 'r') as f:
                    first_line = f.readline()
                    if not first_line.strip():
                        return False, "Empty file"
            except Exception as e:
                return False, f"Cannot read file: {e}"

        return True, ""

    def _get_processor(self, cache_key: str = "default") -> FedoProcessor:
        """Get or create a processor instance (stateless)."""
        if cache_key not in self._processors:
            self._processors[cache_key] = FedoProcessor()
        return self._processors[cache_key]

    def _get_fedo_config(self, context: UploadContext) -> FedoConfig:
        overrides: Dict[str, Any] = {}
        if isinstance(context.config.get("fedo"), dict):
            overrides.update(context.config["fedo"])
        if isinstance(context.config.get("visualization"), dict):
            overrides.update(context.config["visualization"])
        return get_fedo_config(overrides)

    async def _upload_raw_asset(self, file: UploadFile):
        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")
        return await self.asset_service.upload_file(
            file,
            meta_info={"generated": False, "type": "fedo_raw"}
        )

    async def _read_file_content(self, file: UploadFile) -> bytes:
        await file.seek(0)
        return await file.read()

    async def _upload_generated_bytes(
            self,
            content: bytes,
            filename: str,
            meta_info: Dict[str, Any],
            content_type: Optional[str] = None,
    ):
        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")

        file_obj = UploadFile(
            filename=filename,
            file=io.BytesIO(content),
            headers={"content-type": content_type} if content_type else None
        )

        return await self.asset_service.upload_file(file_obj, meta_info=meta_info)

    def _process_file_with_processor(
            self,
            file_content: bytes,
            fedo_config: FedoConfig,
    ) -> FedoData:
        processor = self._get_processor("in_memory")
        return processor.process_bytes(
            file_bytes=file_content,
            config=fedo_config,
        )

    def _build_process_result(
            self,
            filename: str,
            sample_id: str,
            raw_asset_id: str,
            time_energy_asset_id: str,
            l_omegad_asset_id: str,
            metadata: Dict[str, Any],
            lookup_asset_id: Optional[str] = None,
            data_asset_id: Optional[str] = None,
    ) -> ProcessResult:
        asset_ids = {
            "raw_text": raw_asset_id,
            "time_energy_image": time_energy_asset_id,
            "l_omegad_image": l_omegad_asset_id,
        }
        if lookup_asset_id:
            asset_ids["lookup_table"] = lookup_asset_id
        if data_asset_id:
            asset_ids["data_npz"] = data_asset_id

        return ProcessResult(
            success=True,
            sample_id=sample_id,
            filename=filename,
            asset_ids=asset_ids,
            primary_asset_id=time_energy_asset_id,
            sample_fields={
                "meta_info": {
                    "original_filename": filename,
                    "fedo_metadata": metadata,
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
        Process a FEDO data file.

        Pipeline:
        1. Receive and upload raw text file as asset
        2. Parse raw text file
        3. Calculate physics (L-shell, drift frequency)
        4. Generate visualization images for both views
        5. Upload generated images as assets
        6. Return ProcessResult with asset_ids and primary_asset_id

        Args:
            file: Uploaded file (UploadFile from FastAPI)
            context: Upload context with dataset info
            progress_callback: Optional progress callback

        Returns:
            ProcessResult with asset_ids for raw_text, time_energy_image, l_omegad_image
        """
        filename = file.filename or "unknown"
        sample_id = self.generate_id()

        self.emit(EventType.PROCESS_START, {"filename": filename})

        progress = None
        if progress_callback:
            progress = ProgressInfo(
                current=0, total=6, percentage=0,
                message=f"Starting FEDO processing: {filename}",
                stage="fedo_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            self._update_progress(progress_callback, progress, 1, "Uploading raw data file", "fedo_upload_raw")
            raw_asset = await self._upload_raw_asset(file)

            self._update_progress(progress_callback, progress, 2, "Parsing data file", ProcessingStage.FEDO_PARSE)
            file_content = await self._read_file_content(file)

            fedo_config = self._get_fedo_config(context)

            self._update_progress(progress_callback, progress, 3, "Calculating physics", ProcessingStage.FEDO_PHYSICS)
            result = self._process_file_with_processor(
                file_content=file_content,
                fedo_config=fedo_config,
            )

            self._update_progress(progress_callback, progress, 4, "Generating visualizations", "fedo_viz")

            time_energy_asset = await self._upload_generated_bytes(
                content=result.time_energy_image_bytes,
                filename="time_energy.png",
                content_type="image/png",
                meta_info={
                    "generated": True,
                    "type": "fedo_visualization",
                    "view": "time-energy",
                }
            )

            l_omegad_asset = await self._upload_generated_bytes(
                content=result.l_wd_image_bytes,
                filename="l_omegad.png",
                content_type="image/png",
                meta_info={
                    "generated": True,
                    "type": "fedo_visualization",
                    "view": "L-omegad",
                }
            )

            lookup_asset = await self._upload_generated_bytes(
                content=result.lookup_table_bytes,
                filename="lookup.npz",
                content_type="application/octet-stream",
                meta_info={
                    "generated": True,
                    "type": "fedo_lookup_table",
                }
            )

            data_asset = await self._upload_generated_bytes(
                content=result.data_bytes,
                filename="data.npz",
                content_type="application/octet-stream",
                meta_info={
                    "generated": True,
                    "type": "fedo_data",
                }
            )

            self._update_progress(progress_callback, progress, 5, "Finalizing", "fedo_finalize")
            self._update_progress(progress_callback, progress, 6, "Processing complete", "fedo_complete")

            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": sample_id,
                "raw_asset_id": str(raw_asset.id),
                "time_energy_asset_id": str(time_energy_asset.id),
                "l_omegad_asset_id": str(l_omegad_asset.id),
                "lookup_asset_id": str(lookup_asset.id),
                "data_asset_id": str(data_asset.id),
            })

            return self._build_process_result(
                filename=filename,
                sample_id=sample_id,
                raw_asset_id=str(raw_asset.id),
                time_energy_asset_id=str(time_energy_asset.id),
                l_omegad_asset_id=str(l_omegad_asset.id),
                lookup_asset_id=str(lookup_asset.id),
                data_asset_id=str(data_asset.id),
                metadata={
                    **result.metadata,
                    "lookup_asset_id": str(lookup_asset.id),
                    "data_asset_id": str(data_asset.id),
                    "lookup_object_path": lookup_asset.path,
                    "data_object_path": data_asset.path,
                },
            )

        except Exception as e:
            self.logger.error(f"Error processing FEDO file {filename}: {e}", exc_info=True)
            self.emit(EventType.PROCESS_ERROR, {"filename": filename, "error": str(e)})
            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )
