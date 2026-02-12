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

from saki_api.core.config import settings
from saki_api.modules.annotation.extensions.data_formats.fedo.config import FedoConfig, get_fedo_config
# FEDO data processing utilities
from saki_api.modules.annotation.extensions.data_formats.fedo.processor import FedoProcessor, FedoData
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

    def _persist_local_lookup_table(
            self,
            content: bytes,
            context: UploadContext,
            sample_id: str,
    ) -> Optional[str]:
        """
        Persist lookup table to local filesystem for fast access.
        """
        try:
            base_dir = Path(settings.LUT_CACHE_DIR)
            base_dir.mkdir(parents=True, exist_ok=True)
            target_path = base_dir / f"{sample_id}.npz"
            tmp_path = base_dir / f"{sample_id}.npz.tmp"

            tmp_path.write_bytes(content)
            tmp_path.replace(target_path)
            return str(target_path)
        except Exception as e:
            self.logger.warning("本地查找表持久化失败 error={}", e)
            return None

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

    @staticmethod
    def _create_progress_state(
            *,
            filename: str,
            progress_callback: Optional[ProgressCallback],
    ) -> Optional[ProgressInfo]:
        if not progress_callback:
            return None
        progress = ProgressInfo(
            current=0,
            total=6,
            percentage=0,
            message=f"Starting FEDO processing: {filename}",
            stage="fedo_process",
        )
        progress_callback(EventType.PROCESS_PROGRESS, progress)
        return progress

    async def _upload_generated_assets(
            self,
            *,
            fedo_data: FedoData,
            context: UploadContext,
            sample_id: str,
    ) -> dict[str, Any]:
        time_energy_asset = await self._upload_generated_bytes(
            content=fedo_data.time_energy_image_bytes,
            filename="time_energy.png",
            content_type="image/png",
            meta_info={
                "generated": True,
                "type": "fedo_visualization",
                "view": "time-energy",
            },
        )
        l_omegad_asset = await self._upload_generated_bytes(
            content=fedo_data.l_wd_image_bytes,
            filename="l_omegad.png",
            content_type="image/png",
            meta_info={
                "generated": True,
                "type": "fedo_visualization",
                "view": "L-omegad",
            },
        )
        lookup_asset = await self._upload_generated_bytes(
            content=fedo_data.lookup_table_bytes,
            filename="lookup.npz",
            content_type="application/octet-stream",
            meta_info={
                "generated": True,
                "type": "fedo_lookup_table",
            },
        )
        lookup_local_path = self._persist_local_lookup_table(
            content=fedo_data.lookup_table_bytes,
            context=context,
            sample_id=sample_id,
        )
        data_asset = await self._upload_generated_bytes(
            content=fedo_data.data_bytes,
            filename="data.npz",
            content_type="application/octet-stream",
            meta_info={
                "generated": True,
                "type": "fedo_data",
            },
        )
        return {
            "time_energy_asset": time_energy_asset,
            "l_omegad_asset": l_omegad_asset,
            "lookup_asset": lookup_asset,
            "data_asset": data_asset,
            "lookup_local_path": lookup_local_path,
        }

    @staticmethod
    def _build_result_metadata(
            *,
            fedo_metadata: dict[str, Any],
            lookup_asset,
            data_asset,
            lookup_local_path: Optional[str],
    ) -> dict[str, Any]:
        return {
            **fedo_metadata,
            "lookup_asset_id": str(lookup_asset.id),
            "data_asset_id": str(data_asset.id),
            "lookup_object_path": lookup_asset.path,
            "data_object_path": data_asset.path,
            "lookup_local_path": lookup_local_path,
        }

    def _emit_process_complete_event(
            self,
            *,
            filename: str,
            sample_id: str,
            raw_asset,
            time_energy_asset,
            l_omegad_asset,
            lookup_asset,
            data_asset,
    ) -> None:
        self.emit(
            EventType.PROCESS_COMPLETE,
            {
                "filename": filename,
                "sample_id": sample_id,
                "raw_asset_id": str(raw_asset.id),
                "time_energy_asset_id": str(time_energy_asset.id),
                "l_omegad_asset_id": str(l_omegad_asset.id),
                "lookup_asset_id": str(lookup_asset.id),
                "data_asset_id": str(data_asset.id),
            },
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
        progress = self._create_progress_state(
            filename=filename,
            progress_callback=progress_callback,
        )

        try:
            self._update_progress(progress_callback, progress, 1, "Uploading raw data file", "fedo_upload_raw")
            raw_asset = await self._upload_raw_asset(file)

            self._update_progress(progress_callback, progress, 2, "Parsing data file", ProcessingStage.FEDO_PARSE)
            file_content = await self._read_file_content(file)

            fedo_config = self._get_fedo_config(context)

            self._update_progress(progress_callback, progress, 3, "Calculating physics", ProcessingStage.FEDO_PHYSICS)
            fedo_data = self._process_file_with_processor(
                file_content=file_content,
                fedo_config=fedo_config,
            )

            self._update_progress(progress_callback, progress, 4, "Generating visualizations", "fedo_viz")
            generated_assets = await self._upload_generated_assets(
                fedo_data=fedo_data,
                context=context,
                sample_id=sample_id,
            )
            time_energy_asset = generated_assets["time_energy_asset"]
            l_omegad_asset = generated_assets["l_omegad_asset"]
            lookup_asset = generated_assets["lookup_asset"]
            data_asset = generated_assets["data_asset"]
            lookup_local_path = generated_assets["lookup_local_path"]

            self._update_progress(progress_callback, progress, 5, "Finalizing", "fedo_finalize")
            self._update_progress(progress_callback, progress, 6, "Processing complete", "fedo_complete")

            self._emit_process_complete_event(
                filename=filename,
                sample_id=sample_id,
                raw_asset=raw_asset,
                time_energy_asset=time_energy_asset,
                l_omegad_asset=l_omegad_asset,
                lookup_asset=lookup_asset,
                data_asset=data_asset,
            )

            return self._build_process_result(
                filename=filename,
                sample_id=sample_id,
                raw_asset_id=str(raw_asset.id),
                time_energy_asset_id=str(time_energy_asset.id),
                l_omegad_asset_id=str(l_omegad_asset.id),
                lookup_asset_id=str(lookup_asset.id),
                data_asset_id=str(data_asset.id),
                metadata=self._build_result_metadata(
                    fedo_metadata=fedo_data.metadata,
                    lookup_asset=lookup_asset,
                    data_asset=data_asset,
                    lookup_local_path=lookup_local_path,
                ),
            )

        except Exception as e:
            self.logger.exception("处理 FEDO 文件失败 filename={} error={}", filename, e)
            self.emit(EventType.PROCESS_ERROR, {"filename": filename, "error": str(e)})
            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )
