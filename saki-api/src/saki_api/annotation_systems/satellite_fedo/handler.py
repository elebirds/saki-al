"""
FEDO annotation system handler.
Implements AnnotationSystemHandler for satellite FEDO data processing.
"""

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
from .processor import FedoProcessor


@register_handler
class FedoHandler(AnnotationSystemHandler):
    """
    Handler for FEDO (satellite electron energy data) annotation system.
    
    Processes uploaded FEDO text files through:
    1. Parsing raw data
    2. Physics calculations (L-shell, drift frequency)
    3. Generating visualization images
    4. Creating coordinate lookup tables
    """

    system_type = AnnotationSystemType.FEDO

    def __init__(self):
        super().__init__()
        self._processors: Dict[str, FedoProcessor] = {}

    def _get_processor(self, storage_path: str) -> FedoProcessor:
        """Get or create a processor for the given storage path."""
        if storage_path not in self._processors:
            self._processors[storage_path] = FedoProcessor(storage_path)
        return self._processors[storage_path]

    @property
    def support_extensions(self) -> set[str]:
        return {'.txt'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        state, reason = super().validate_file(file_path, context)
        if state != True:
            return state, reason

        # Basic validation: check if file starts with expected format
        try:
            with open(file_path, 'r') as f:
                first_line = f.readline()
                # FEDO files should have specific format
                # This is a basic check, more thorough validation happens in parser
                if not first_line.strip():
                    return False, "Empty file"
        except Exception as e:
            return False, f"Cannot read file: {e}"

        return True, ""

    def process_upload(
            self,
            file_path: Path,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a FEDO data file.
        
        Args:
            file_path: Path to the uploaded FEDO text file
            context: Upload context with project configuration
            progress_callback: Optional callback for progress updates
            
        Returns:
            ProcessResult with processing status and sample data
        """
        filename = file_path.name

        # Emit processing start event
        self.emit(EventType.PROCESS_START, {"filename": filename})

        # Report progress
        if progress_callback:
            progress = ProgressInfo(
                current=0, total=4, percentage=0,
                message=f"Starting FEDO processing: {filename}",
                stage="fedo_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            # Get visualization config from project settings
            viz_config = context.annotation_config.get('visualization', {})
            dpi = viz_config.get('dpi', 200)
            l_xlim = tuple(viz_config.get('l_xlim', [1.2, 1.9]))
            wd_ylim = tuple(viz_config.get('wd_ylim', [0.0, 4.0]))

            # Get processor for this project's storage
            storage_path = str(context.upload_dir / "processed")
            processor = self._get_processor(storage_path)

            # Process the file
            if progress_callback:
                progress.update(1, "Parsing data file", "fedo_parse")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            result = processor.process_file(
                str(file_path),
                dpi=dpi,
                l_xlim=l_xlim,
                wd_ylim=wd_ylim,
            )

            if progress_callback:
                progress.update(4, "Processing complete", "fedo_complete")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            # Emit completion event
            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": result['sample_id'],
            })

            return ProcessResult(
                success=True,
                sample_id=result['sample_id'],
                filename=filename,
                sample_data={
                    'parquet_path': result['parquet_path'],
                    'time_energy_image_path': result['time_energy_image_path'],
                    'l_wd_image_path': result['l_wd_image_path'],
                    'lookup_table_path': result['lookup_table_path'],
                },
                metadata=result['metadata'],
            )

        except Exception as e:
            self.logger.error(f"Error processing FEDO file {filename}: {e}")
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
        Get fields to set on the Sample model from FEDO processing result.
        
        Returns fields specific to FEDO samples:
        - parquet_path
        - time_energy_image_path
        - l_wd_image_path
        - lookup_table_path
        - meta_data
        """
        if not result.success:
            return {}

        return {
            'parquet_path': result.sample_data.get('parquet_path'),
            'time_energy_image_path': result.sample_data.get('time_energy_image_path'),
            'l_wd_image_path': result.sample_data.get('l_wd_image_path'),
            'lookup_table_path': result.sample_data.get('lookup_table_path'),
            'meta_data': result.metadata,
        }

    def on_annotation_save(
            self,
            sample_id: str,
            annotation_data: Dict[str, Any],
            context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process FEDO annotation data before saving.
        
        FEDO annotations may include coordinate transformations
        or additional physics calculations.
        """
        # Call parent to emit event
        annotation_data = super().on_annotation_save(sample_id, annotation_data, context)

        # FEDO-specific annotation processing can be added here
        # For example, validating L-shell values or drift frequencies

        return annotation_data
