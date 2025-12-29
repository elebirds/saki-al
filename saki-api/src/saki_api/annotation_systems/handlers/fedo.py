"""
FEDO annotation system handler.
Handles satellite FEDO (electron flux) data annotation with dual-view mapping.

This handler provides:
- FEDO text file upload and processing (parsing, physics, visualization)
- Dual-view annotation sync with automatic mapping between views
- Linked annotation management (manual → auto-generated)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from saki_api.annotation_systems.base import (
    AnnotationSystemHandler,
    AnnotationContext,
    EventType,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    SyncResult,
    UploadContext,
)
from saki_api.annotation_systems.registry import register_handler
from saki_api.models.enums import AnnotationSystemType, AnnotationType, AnnotationSource

# FEDO data processing utilities (in satellite_fedo submodule)
from saki_api.annotation_systems.satellite_fedo.processor import FedoProcessor


# FEDO view identifiers
VIEW_TIME_ENERGY = "time-energy"
VIEW_L_OMEGAD = "L-omegad"


@register_handler
class FedoHandler(AnnotationSystemHandler):
    """
    Handler for FEDO satellite data annotation system.
    
    FEDO uses dual-view annotation:
    - Time-Energy view: Energy flux vs time
    - L-Omegad view: L-shell vs drift frequency
    
    When user annotates in one view, the system maps the annotation
    to the corresponding region in the other view via point-set mapping.
    This creates:
    - Manual annotation (source=MANUAL) in the annotated view
    - Auto-generated annotation(s) (source=AUTO) in the other view
    
    The auto-generated annotations store parent reference in extra:
        extra: { parent_id: "<manual_ann_id>", view: "L-omegad", ... }
    """

    system_type = AnnotationSystemType.FEDO

    def __init__(self):
        super().__init__()
        self._processors: Dict[str, FedoProcessor] = {}

    @property
    def supported_extensions(self) -> set[str]:
        return {'.txt'}

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        is_valid, error = super().validate_file(file_path, context)
        if not is_valid:
            return is_valid, error

        # Check FEDO file format
        try:
            with open(file_path, 'r') as f:
                first_line = f.readline()
                if not first_line.strip():
                    return False, "Empty file"
        except Exception as e:
            return False, f"Cannot read file: {e}"

        return True, ""

    def _get_processor(self, storage_path: str) -> FedoProcessor:
        """Get or create a processor for the storage path."""
        if storage_path not in self._processors:
            self._processors[storage_path] = FedoProcessor(storage_path)
        return self._processors[storage_path]

    # ==================== Upload & Processing ====================

    def process_upload(
        self,
        file_path: Path,
        context: UploadContext,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a FEDO data file.
        
        Pipeline:
        1. Parse raw text file
        2. Calculate physics (L-shell, drift frequency)
        3. Generate visualization images for both views
        4. Generate coordinate lookup table for mapping
        """
        filename = file_path.name

        self.emit(EventType.PROCESS_START, {"filename": filename})

        if progress_callback:
            progress = ProgressInfo(
                current=0, total=4, percentage=0,
                message=f"Starting FEDO processing: {filename}",
                stage="fedo_process"
            )
            progress_callback(EventType.PROCESS_PROGRESS, progress)

        try:
            # Get visualization config
            viz_config = context.config.get('visualization', {})
            dpi = viz_config.get('dpi', 200)
            l_xlim = tuple(viz_config.get('l_xlim', [1.2, 1.9]))
            wd_ylim = tuple(viz_config.get('wd_ylim', [0.0, 4.0]))

            # Get processor
            storage_path = str(context.upload_dir / "processed")
            processor = self._get_processor(storage_path)

            if progress_callback:
                progress.update(1, "Parsing data file", "fedo_parse")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            # Process the file
            result = processor.process_file(
                str(file_path),
                dpi=dpi,
                l_xlim=l_xlim,
                wd_ylim=wd_ylim,
            )

            if progress_callback:
                progress.update(4, "Processing complete", "fedo_complete")
                progress_callback(EventType.PROCESS_PROGRESS, progress)

            self.emit(EventType.PROCESS_COMPLETE, {
                "filename": filename,
                "sample_id": result['sample_id'],
            })

            # Convert paths to static URLs
            sample_id = result['sample_id']
            base_url = f"/static/{context.dataset_id}/processed/{sample_id}"

            return ProcessResult(
                success=True,
                sample_id=sample_id,
                filename=filename,
                sample_fields={
                    'url': f"{base_url}/view_time_energy.png",
                    'meta_data': {
                        'original_filename': filename,
                        'time_energy_image_url': f"{base_url}/view_time_energy.png",
                        'l_wd_image_url': f"{base_url}/view_l_wd.png",
                        'lookup_table_url': f"{base_url}/lookup.parquet",
                        'parquet_url': f"{base_url}/data.parquet",
                        **result['metadata'],
                    },
                },
            )

        except Exception as e:
            self.logger.error(f"Error processing FEDO file {filename}: {e}")
            self.emit(EventType.PROCESS_ERROR, {"filename": filename, "error": str(e)})
            return ProcessResult(
                success=False,
                filename=filename,
                error=str(e),
            )

    # ==================== Annotation Sync (Dual-View Mapping) ====================

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
        Handle FEDO annotation creation with dual-view mapping.
        
        When user creates an annotation in one view:
        1. Validate the annotation
        2. Map geometry to the other view via lookup table
        3. Generate linked auto-annotation(s)
        """
        view = extra.get('view')
        
        if view not in (VIEW_TIME_ENERGY, VIEW_L_OMEGAD):
            return SyncResult(
                success=False,
                annotation_id=annotation_id,
                action="create",
                error=f"Invalid view: {view}. Must be '{VIEW_TIME_ENERGY}' or '{VIEW_L_OMEGAD}'",
            )

        # Determine target view
        target_view = VIEW_L_OMEGAD if view == VIEW_TIME_ENERGY else VIEW_TIME_ENERGY

        # Generate mapped annotations
        generated = self._generate_mapped_annotations(
            parent_id=annotation_id,
            label_id=label_id,
            ann_type=ann_type,
            source_view=view,
            target_view=target_view,
            data=data,
            context=context,
        )

        self.logger.info(
            f"FEDO annotation created: {annotation_id} in {view}, "
            f"generated {len(generated)} mapped annotations in {target_view}"
        )

        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="create",
            generated=generated,
        )

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
        Handle FEDO annotation update.
        
        If geometry changed, linked annotations need to be regenerated.
        """
        # If data changed, regenerated annotations should replace old ones
        regenerate = data is not None
        
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="update",
            # Extra info for frontend to know regeneration is needed
            generated=[{"_action": "regenerate_children"}] if regenerate else [],
        )

    def on_annotation_delete(
        self,
        annotation_id: str,
        extra: Dict[str, Any],
        context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle FEDO annotation deletion.
        
        When a manual annotation is deleted, all linked auto-annotations
        should also be deleted. Frontend should handle this based on parent_id.
        """
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="delete",
            # Signal that child annotations should be deleted
            generated=[{"_action": "delete_children", "parent_id": annotation_id}],
        )

    # ==================== Mapping Logic ====================

    def _generate_mapped_annotations(
        self,
        parent_id: str,
        label_id: str,
        ann_type: AnnotationType,
        source_view: str,
        target_view: str,
        data: Dict[str, Any],
        context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """
        Generate mapped annotations in the target view.
        
        TODO: Implement actual point-set mapping using FEDO lookup tables.
        This is a PLACEHOLDER that returns a sample OBB at 0.5x width.
        
        The actual implementation should:
        1. Load lookup table from context.sample_meta
        2. Map annotation geometry through coordinate transform
        3. Generate OBB(s) in target view coordinates
        
        Note: One manual annotation may produce multiple auto annotations
        due to non-linear mapping.
        """
        # ================================================================
        # PLACEHOLDER IMPLEMENTATION
        # Replace with actual FEDO point-set mapping logic
        # ================================================================
        
        generated = []
        
        if 'x' in data and 'y' in data:
            generated_id = self.generate_id()
            
            # Placeholder: simple transform (not real physics)
            generated.append({
                "id": generated_id,
                "label_id": label_id,
                "type": AnnotationType.OBB.value,
                "source": AnnotationSource.AUTO.value,
                "data": {
                    "x": data.get('x', 0) * 0.8,
                    "y": data.get('y', 0) * 0.6,
                    "width": data.get('width', 100) * 0.5,  # 0.5x width
                    "height": data.get('height', 50) * 0.7,
                    "rotation": data.get('rotation', 0) + 15,
                },
                "extra": {
                    "parent_id": parent_id,
                    "view": target_view,
                    "mapping_method": "placeholder",
                },
            })

        return generated

    def on_batch_save(
        self,
        annotations: List[Dict[str, Any]],
        context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """
        Validate parent-child relationships before batch save.
        """
        annotation_ids = {a.get('id') for a in annotations}
        
        for ann in annotations:
            parent_id = ann.get('extra', {}).get('parent_id')
            if parent_id and parent_id not in annotation_ids:
                self.logger.warning(
                    f"Annotation {ann.get('id')} has parent_id {parent_id} "
                    f"not in save batch"
                )

        return annotations
