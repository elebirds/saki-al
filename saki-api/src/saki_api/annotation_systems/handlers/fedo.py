"""
FEDO annotation system handler.
Handles satellite FEDO (electron flux) data annotation with dual-view mapping.

This handler provides:
- FEDO text file upload and processing (parsing, physics, visualization)
- Dual-view annotation sync with automatic mapping between views
- Linked annotation management (manual → auto-generated)
"""

import os
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

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
from saki_api.annotation_systems.satellite_fedo.lookup import load_lookup_table, LookupTable


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
        # If data is None, no geometry change, no need to regenerate
        if data is None:
            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="update",
                generated=[],
            )
        
        # Get the view from extra
        view = extra.get('view') if extra else None
        if view not in (VIEW_TIME_ENERGY, VIEW_L_OMEGAD):
            # Default to time-energy if view is not provided
            view = VIEW_TIME_ENERGY
        
        # Determine target view
        target_view = VIEW_L_OMEGAD if view == VIEW_TIME_ENERGY else VIEW_TIME_ENERGY
        
        # For update, we need label_id and ann_type to regenerate annotations
        # If not provided, we cannot regenerate, so return signal
        if not label_id or not ann_type:
            self.logger.warning(
                f"FEDO annotation update: {annotation_id} missing label_id or ann_type, "
                f"cannot regenerate mapped annotations"
            )
            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="update",
                generated=[{"_action": "regenerate_children"}],  # Signal frontend to handle
            )
        
        # Generate mapped annotations (same logic as create)
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
            f"FEDO annotation updated: {annotation_id} in {view}, "
            f"regenerated {len(generated)} mapped annotations in {target_view}"
        )
        
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="update",
            generated=generated,
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

    def _load_lookup_table(self, context: AnnotationContext) -> Optional[LookupTable]:
        """Load lookup table from sample metadata."""
        try:
            meta = context.sample_meta
            lookup_url = meta.get('lookup_table_url')
            if not lookup_url:
                self.logger.warning(f"No lookup_table_url in sample_meta for {context.sample_id}")
                return None
            
            # Convert URL to file path
            # URL format: /static/{dataset_id}/processed/{sample_id}/lookup.parquet
            # Need to resolve to actual file path
            # Assuming UPLOAD_DIR is configured in settings
            from saki_api.core.config import settings
            lookup_path = os.path.join(settings.UPLOAD_DIR, lookup_url.lstrip('/static/'))
            
            if not os.path.exists(lookup_path):
                self.logger.error(f"Lookup table not found: {lookup_path}")
                return None
            
            return load_lookup_table(lookup_path)
        except Exception as e:
            self.logger.error(f"Error loading lookup table: {e}")
            return None

    def _get_image_config(self, context: AnnotationContext) -> Dict[str, Any]:
        """Get image configuration from sample metadata."""
        meta = context.sample_meta
        viz_config = meta.get('visualization_config', {})
        return {
            'dpi': viz_config.get('dpi', 200),
            'l_xlim': tuple(viz_config.get('l_xlim', [1.2, 1.9])),
            'wd_ylim': tuple(viz_config.get('wd_ylim', [0.0, 4.0])),
        }

    def _pixel_to_physical_te(
        self, 
        x: float, 
        y: float, 
        image_width: float, 
        image_height: float,
        lookup: LookupTable
    ) -> Tuple[float, float]:
        """Convert pixel coordinates to Time-Energy physical coordinates."""
        # Time axis: x pixel -> time index -> datetime
        # Energy axis: y pixel -> energy index (log scale)
        
        # Normalize pixel coordinates to [0, 1]
        x_norm = x / image_width
        y_norm = y / image_height
        
        # Time: linear mapping from [0, 1] to [0, n_time-1]
        time_idx = x_norm * (lookup.n_time - 1)
        time_idx = np.clip(time_idx, 0, lookup.n_time - 1)
        
        # Energy: log scale mapping from [0, 1] to energy range
        # Energy is displayed on log scale, so we need to map y_norm to log space
        E_min = lookup.E.min()
        E_max = lookup.E.max()
        log_E_min = np.log10(E_min)
        log_E_max = np.log10(E_max)
        log_E = log_E_min + (1 - y_norm) * (log_E_max - log_E_min)  # y=0 is top (max energy)
        E = 10 ** log_E
        
        # Get time value (convert index to datetime)
        time_idx_int = int(np.clip(time_idx, 0, lookup.n_time - 1))
        time_ns = lookup.time_stamps[time_idx_int]
        time_val = time_ns  # Keep as nanoseconds for now
        
        return time_val, E

    def _pixel_to_physical_lwd(
        self,
        x: float,
        y: float,
        image_width: float,
        image_height: float,
        lookup: LookupTable,
        config: Dict[str, Any]
    ) -> Tuple[float, float]:
        """Convert pixel coordinates to L-ωd physical coordinates."""
        # L axis: x pixel -> L value (linear)
        # ωd axis: y pixel -> ωd value (linear)
        
        x_norm = x / image_width
        y_norm = y / image_height
        
        l_xlim = config['l_xlim']
        wd_ylim = config['wd_ylim']
        
        # L: linear mapping
        L = l_xlim[0] + x_norm * (l_xlim[1] - l_xlim[0])
        
        # ωd: linear mapping (y=0 is bottom, y=1 is top)
        Wd = wd_ylim[0] + (1 - y_norm) * (wd_ylim[1] - wd_ylim[0])
        
        return L, Wd

    def _physical_to_pixel_te(
        self,
        time_val: float,
        E: float,
        image_width: float,
        image_height: float,
        lookup: LookupTable
    ) -> Tuple[float, float]:
        """Convert Time-Energy physical coordinates to pixel coordinates."""
        # Find closest time index
        time_idx = np.searchsorted(lookup.time_stamps, time_val)
        time_idx = np.clip(time_idx, 0, lookup.n_time - 1)
        x_norm = time_idx / (lookup.n_time - 1) if lookup.n_time > 1 else 0
        
        # Energy: log scale
        E_min = lookup.E.min()
        E_max = lookup.E.max()
        log_E_min = np.log10(E_min)
        log_E_max = np.log10(E_max)
        log_E = np.log10(np.clip(E, E_min, E_max))
        y_norm = 1 - (log_E - log_E_min) / (log_E_max - log_E_min) if log_E_max > log_E_min else 0.5
        
        return x_norm * image_width, y_norm * image_height

    def _physical_to_pixel_lwd(
        self,
        L: float,
        Wd: float,
        image_width: float,
        image_height: float,
        config: Dict[str, Any]
    ) -> Tuple[float, float]:
        """Convert L-ωd physical coordinates to pixel coordinates."""
        l_xlim = config['l_xlim']
        wd_ylim = config['wd_ylim']
        
        # L: linear mapping
        x_norm = (L - l_xlim[0]) / (l_xlim[1] - l_xlim[0]) if l_xlim[1] > l_xlim[0] else 0.5
        x_norm = np.clip(x_norm, 0, 1)
        
        # ωd: linear mapping (y=0 is bottom)
        y_norm = 1 - (Wd - wd_ylim[0]) / (wd_ylim[1] - wd_ylim[0]) if wd_ylim[1] > wd_ylim[0] else 0.5
        y_norm = np.clip(y_norm, 0, 1)
        
        return x_norm * image_width, y_norm * image_height

    def _get_bbox_points(self, data: Dict[str, Any], ann_type: AnnotationType) -> np.ndarray:
        """Get all points within a bounding box."""
        x = data.get('x', 0)
        y = data.get('y', 0)
        width = data.get('width', 0)
        height = data.get('height', 0)
        rotation = data.get('rotation', 0)
        
        # Create rectangle corners
        corners = np.array([
            [-width/2, -height/2],
            [width/2, -height/2],
            [width/2, height/2],
            [-width/2, height/2]
        ])
        
        # Apply rotation
        if rotation != 0:
            angle_rad = np.deg2rad(rotation)
            cos_a = np.cos(angle_rad)
            sin_a = np.sin(angle_rad)
            rotation_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
            corners = corners @ rotation_matrix.T
        
        # Translate to center
        corners[:, 0] += x
        corners[:, 1] += y
        
        # Sample points within the bbox (for better coverage)
        # Create a grid of points
        n_samples = 20  # Sample density
        x_samples = np.linspace(-width/2, width/2, n_samples)
        y_samples = np.linspace(-height/2, height/2, n_samples)
        xx, yy = np.meshgrid(x_samples, y_samples)
        points = np.column_stack([xx.ravel(), yy.ravel()])
        
        # Apply rotation and translation
        if rotation != 0:
            points = points @ rotation_matrix.T
        points[:, 0] += x
        points[:, 1] += y
        
        return points

    def _find_data_indices_te_range(
        self,
        time_min: float,
        time_max: float,
        E_min: float,
        E_max: float,
        lookup: LookupTable
    ) -> List[Tuple[int, int]]:
        """Find all data indices (i, j) within Time-Energy range."""
        indices = []
        
        # Find time index range
        time_idx_min = np.searchsorted(lookup.time_stamps, time_min)
        time_idx_max = np.searchsorted(lookup.time_stamps, time_max)
        time_idx_min = max(0, time_idx_min - 1)  # Include boundary
        time_idx_max = min(lookup.n_time - 1, time_idx_max + 1)
        
        # Find energy index range
        E_min_idx = np.searchsorted(lookup.E, E_min)
        E_max_idx = np.searchsorted(lookup.E, E_max)
        E_min_idx = max(0, E_min_idx - 1)
        E_max_idx = min(lookup.n_energy - 1, E_max_idx + 1)
        
        # Get all indices in range
        for i in range(time_idx_min, time_idx_max + 1):
            for j in range(E_min_idx, E_max_idx + 1):
                # Verify point is actually in range
                time_val = lookup.time_stamps[i]
                E_val = lookup.E[j]
                if time_min <= time_val <= time_max and E_min <= E_val <= E_max:
                    indices.append((int(i), int(j)))
        
        return indices if indices else [(int(time_idx_min), int(E_min_idx))]

    def _find_data_indices_lwd_range(
        self,
        L_min: float,
        L_max: float,
        Wd_min: float,
        Wd_max: float,
        lookup: LookupTable,
        config: Dict[str, Any]
    ) -> List[Tuple[int, int]]:
        """Find all data indices (i, j) within L-ωd range."""
        indices = []
        
        # Find all time indices where L is in range
        valid_time_indices = np.where((lookup.L >= L_min) & (lookup.L <= L_max))[0]
        
        if len(valid_time_indices) == 0:
            # Fallback: find closest L
            L_center = (L_min + L_max) / 2
            L_diff = np.abs(lookup.L - L_center)
            valid_time_indices = [np.argmin(L_diff)]
        
        # For each valid time index, find energy indices where Wd is in range
        for i in valid_time_indices:
            valid_energy_indices = np.where((lookup.Wd[i, :] >= Wd_min) & (lookup.Wd[i, :] <= Wd_max))[0]
            if len(valid_energy_indices) == 0:
                # Fallback: find closest Wd
                Wd_center = (Wd_min + Wd_max) / 2
                Wd_diff = np.abs(lookup.Wd[i, :] - Wd_center)
                valid_energy_indices = [np.argmin(Wd_diff)]
            
            for j in valid_energy_indices:
                indices.append((int(i), int(j)))
        
        return indices if indices else [(int(valid_time_indices[0]), 0)]

    def _indices_to_physical_te(
        self,
        indices: List[Tuple[int, int]],
        lookup: LookupTable
    ) -> np.ndarray:
        """Convert data indices to Time-Energy physical coordinates."""
        coords = []
        for i, j in indices:
            i = np.clip(i, 0, lookup.n_time - 1)
            j = np.clip(j, 0, lookup.n_energy - 1)
            time_val = lookup.time_stamps[i]
            E = lookup.E[j]
            coords.append([time_val, E])
        return np.array(coords)

    def _indices_to_physical_lwd(
        self,
        indices: List[Tuple[int, int]],
        lookup: LookupTable
    ) -> np.ndarray:
        """Convert data indices to L-ωd physical coordinates."""
        coords = []
        for i, j in indices:
            i = np.clip(i, 0, lookup.n_time - 1)
            j = np.clip(j, 0, lookup.n_energy - 1)
            L = lookup.L[i]
            Wd = lookup.Wd[i, j]
            coords.append([L, Wd])
        return np.array(coords)

    def _compute_minimum_bounding_boxes(
        self,
        points: np.ndarray,
        min_points: int = 3
    ) -> List[Dict[str, Any]]:
        """Compute minimum bounding boxes for clustered points."""
        if len(points) < min_points:
            # Too few points, return simple bbox
            if len(points) == 0:
                return []
            x_min, y_min = points.min(axis=0)
            x_max, y_max = points.max(axis=0)
            return [{
                'x': (x_min + x_max) / 2,
                'y': (y_min + y_max) / 2,
                'width': x_max - x_min,
                'height': y_max - y_min,
                'rotation': 0
            }]
        
        # Simple clustering: divide space into grid cells
        # This is a simplified approach that works without scipy/sklearn
        if len(points) < min_points:
            # Too few points, return simple bbox
            x_min, y_min = points.min(axis=0)
            x_max, y_max = points.max(axis=0)
            return [{
                'x': (x_min + x_max) / 2,
                'y': (y_min + y_max) / 2,
                'width': x_max - x_min,
                'height': y_max - y_min,
                'rotation': 0
            }]
        
        # Compute adaptive grid size based on point spread
        x_range = points[:, 0].max() - points[:, 0].min()
        y_range = points[:, 1].max() - points[:, 1].min()
        grid_size = max(x_range, y_range) / 5  # Divide into ~5x5 grid
        
        # Assign points to grid cells
        x_min = points[:, 0].min()
        y_min = points[:, 1].min()
        grid_cells = {}
        for point in points:
            cell_x = int((point[0] - x_min) / grid_size)
            cell_y = int((point[1] - y_min) / grid_size)
            cell_key = (cell_x, cell_y)
            if cell_key not in grid_cells:
                grid_cells[cell_key] = []
            grid_cells[cell_key].append(point)
        
        # Generate bbox for each cell with enough points
        bboxes = []
        for cell_points in grid_cells.values():
            if len(cell_points) < min_points:
                continue
            
            cell_points = np.array(cell_points)
            
            # Try to find minimum area rectangle
            # Simple approach: try different rotation angles
            min_area = float('inf')
            best_bbox = None
            
            # Try rotations in 5-degree steps
            for angle_deg in range(0, 180, 5):
                angle_rad = np.deg2rad(angle_deg)
                cos_a = np.cos(angle_rad)
                sin_a = np.sin(angle_rad)
                rotation_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
                
                # Rotate points
                rotated = cell_points @ rotation_matrix.T
                
                # Compute axis-aligned bbox
                x_min_rot, y_min_rot = rotated.min(axis=0)
                x_max_rot, y_max_rot = rotated.max(axis=0)
                width = x_max_rot - x_min_rot
                height = y_max_rot - y_min_rot
                area = width * height
                
                if area < min_area:
                    min_area = area
                    center_rot = np.array([(x_min_rot + x_max_rot) / 2, (y_min_rot + y_max_rot) / 2])
                    # Rotate center back
                    inv_matrix = np.array([[cos_a, sin_a], [-sin_a, cos_a]])
                    center = center_rot @ inv_matrix.T
                    
                    best_bbox = {
                        'x': center[0],
                        'y': center[1],
                        'width': width,
                        'height': height,
                        'rotation': angle_deg
                    }
            
            if best_bbox:
                bboxes.append(best_bbox)
        
        return bboxes if bboxes else [{
            'x': points[:, 0].mean(),
            'y': points[:, 1].mean(),
            'width': points[:, 0].max() - points[:, 0].min(),
            'height': points[:, 1].max() - points[:, 1].min(),
            'rotation': 0
        }]

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
        Generate mapped annotations in the target view using real FEDO lookup tables.
        
        Implementation:
        1. Load lookup table from sample metadata
        2. Convert pixel coordinates to physical coordinates (source view)
        3. Find corresponding data indices (i, j)
        4. Map to target view physical coordinates
        5. Cluster points and compute minimum bounding boxes (may be multiple)
        6. Convert back to pixel coordinates
        """
        # Load lookup table
        lookup = self._load_lookup_table(context)
        if not lookup:
            self.logger.warning(f"Cannot load lookup table for {context.sample_id}, using placeholder")
            return self._generate_placeholder_annotation(parent_id, label_id, data, target_view)
        
        config = self._get_image_config(context)
        
        # Estimate image dimensions (from DPI and data size)
        # For now, use a reasonable default based on typical image sizes
        # In production, these should come from actual image metadata
        image_width = 1200  # Typical width for FEDO images
        image_height = 800  # Typical height for FEDO images
        
        # Get all points in the source bbox
        source_points = self._get_bbox_points(data, ann_type)
        
        # Convert source bbox to physical coordinate ranges
        if source_view == VIEW_TIME_ENERGY:
            # Get bbox corners in physical coordinates
            corners_physical = []
            for px, py in source_points:
                time_val, E = self._pixel_to_physical_te(px, py, image_width, image_height, lookup)
                corners_physical.append([time_val, E])
            corners_physical = np.array(corners_physical)
            
            # Get range
            time_min = corners_physical[:, 0].min()
            time_max = corners_physical[:, 0].max()
            E_min = corners_physical[:, 1].min()
            E_max = corners_physical[:, 1].max()
            
            # Find all data indices in range
            all_indices = self._find_data_indices_te_range(time_min, time_max, E_min, E_max, lookup)
            
            # Map to target view (L-ωd) physical coordinates
            target_physical = self._indices_to_physical_lwd(all_indices, lookup)
            
        else:  # source_view == VIEW_L_OMEGAD
            # Get bbox corners in physical coordinates
            corners_physical = []
            for px, py in source_points:
                L, Wd = self._pixel_to_physical_lwd(px, py, image_width, image_height, lookup, config)
                corners_physical.append([L, Wd])
            corners_physical = np.array(corners_physical)
            
            # Get range
            L_min = corners_physical[:, 0].min()
            L_max = corners_physical[:, 0].max()
            Wd_min = corners_physical[:, 1].min()
            Wd_max = corners_physical[:, 1].max()
            
            # Find all data indices in range
            all_indices = self._find_data_indices_lwd_range(L_min, L_max, Wd_min, Wd_max, lookup, config)
            
            # Map to target view (Time-Energy) physical coordinates
            target_physical = self._indices_to_physical_te(all_indices, lookup)
        
        # Convert target physical coordinates to pixel coordinates
        target_pixels = []
        for coord in target_physical:
            if target_view == VIEW_TIME_ENERGY:
                px, py = self._physical_to_pixel_te(coord[0], coord[1], image_width, image_height, lookup)
            else:  # target_view == VIEW_L_OMEGAD
                px, py = self._physical_to_pixel_lwd(coord[0], coord[1], image_width, image_height, config)
            target_pixels.append([px, py])
        target_pixels = np.array(target_pixels)
        
        # Compute minimum bounding boxes (may be multiple due to non-monotonic mapping)
        bboxes = self._compute_minimum_bounding_boxes(target_pixels, min_points=3)
        
        # Generate annotation objects
        generated = []
        for bbox in bboxes:
            generated_id = self.generate_id()
            generated.append({
                "id": generated_id,
                "label_id": label_id,
                "type": AnnotationType.OBB.value if bbox['rotation'] != 0 else AnnotationType.RECT.value,
                "source": AnnotationSource.FEDO_MAPPING.value,
                "data": {
                    "x": float(bbox['x']),
                    "y": float(bbox['y']),
                    "width": float(bbox['width']),
                    "height": float(bbox['height']),
                    "rotation": float(bbox['rotation']),
                },
                "extra": {
                    "parent_id": parent_id,
                    "view": target_view,
                    "mapping_method": "fedo_lookup_table",
                },
            })
        
        if not generated:
            # Fallback to placeholder if no boxes generated
            return self._generate_placeholder_annotation(parent_id, label_id, data, target_view)
        
        return generated

    def _generate_placeholder_annotation(
        self,
        parent_id: str,
        label_id: str,
        data: Dict[str, Any],
        target_view: str
    ) -> List[Dict[str, Any]]:
        """Generate a placeholder annotation when lookup table is unavailable."""
        generated_id = self.generate_id()
        return [{
            "id": generated_id,
            "label_id": label_id,
            "type": AnnotationType.OBB.value,
            "source": AnnotationSource.FEDO_MAPPING.value,
            "data": {
                "x": data.get('x', 0) * 0.8,
                "y": data.get('y', 0) * 0.6,
                "width": data.get('width', 100) * 0.5,
                "height": data.get('height', 50) * 0.7,
                "rotation": data.get('rotation', 0) + 15,
            },
            "extra": {
                "parent_id": parent_id,
                "view": target_view,
                "mapping_method": "placeholder",
            },
        }]

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
