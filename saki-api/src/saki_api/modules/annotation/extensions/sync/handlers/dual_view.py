"""
Dual-view annotation sync handler.

Handles FEDO satellite data with dual-view annotation mapping.
When user annotates in one view, the system maps the annotation
to the corresponding region in the other view via lookup tables.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.annotation.extensions.data_formats.fedo.lookup import load_lookup_table_from_bytes
from saki_api.modules.annotation.extensions.data_formats.fedo.obb_mapper import map_obb_annotations
from saki_api.modules.annotation.extensions.sync.base import (
    BaseAnnotationSyncHandler,
    AnnotationContext,
    SyncResult,
)
from saki_api.modules.annotation.extensions.sync.registry import register_sync_handler
from saki_api.modules.annotation.extensions.view_system.mappers.lut_mapper import LUTViewMapper
from saki_api.modules.shared.modeling.enums import DatasetType, AnnotationType, AnnotationSource

# FEDO view identifiers
VIEW_TIME_ENERGY = "time-energy"
VIEW_L_OMEGAD = "L-omegad"


@register_sync_handler
class DualViewSyncHandler(BaseAnnotationSyncHandler):
    """
    Sync handler for FEDO dual-view annotation.

    FEDO uses dual-view annotation:
    - Time-Energy view: Energy flux vs time
    - L-Omegad view: L-shell vs drift frequency

    When user annotates in one view, the system maps the annotation
    to the corresponding region in the other view via lookup tables.

    This creates:
    - Manual annotation (source=MANUAL) in the annotated view
    - Auto-generated annotation(s) (source=SYSTEM) in the other view

    The auto-generated annotations share the same group_id with the manual annotation
    to represent a single logical group across views.
    """

    system_type = DatasetType.FEDO

    def __init__(self, session: Optional[AsyncSession] = None):
        """Initialize with database session for asset operations."""
        super().__init__(session)
        self._view_mappers: Dict[str, LUTViewMapper] = {}

    def _get_view_mapper(self, sample_meta: Dict[str, Any]) -> Optional[LUTViewMapper]:
        """Get or create a view mapper for the sample."""
        lookup_local_path, lookup_object_path = self._extract_lookup_paths(sample_meta)
        lookup_key = lookup_local_path or lookup_object_path
        if not lookup_key:
            return None

        if lookup_key in self._view_mappers:
            return self._view_mappers[lookup_key]

        try:
            lookup_bytes = None
            if lookup_local_path:
                path = Path(lookup_local_path)
                if path.exists():
                    lookup_bytes = path.read_bytes()

            if lookup_bytes is None:
                if not self.asset_service:
                    raise RuntimeError("AssetService not initialized")
                if not lookup_object_path:
                    raise RuntimeError("lookup_object_path missing")
                lookup_bytes = self.asset_service.storage.get_object_bytes(lookup_object_path)
            lookup_table = load_lookup_table_from_bytes(lookup_bytes)

            mapper = LUTViewMapper(lookup_table=lookup_table)
            self._view_mappers[lookup_key] = mapper
            return mapper
        except Exception as e:
            self.logger.error("加载查找表失败 error={}", e)
            return None

    def _load_lookup_table(self, context: AnnotationContext):
        """Load lookup table from object storage (no disk)."""
        try:
            meta = context.sample_meta or {}
            lookup_local_path, lookup_object_path = self._extract_lookup_paths(meta)

            lookup_bytes = None
            if lookup_local_path:
                path = Path(lookup_local_path)
                if path.exists():
                    lookup_bytes = path.read_bytes()

            if lookup_bytes is None:
                if not lookup_object_path:
                    self.logger.warning("样本缺少查找表路径 sample_id={}", context.sample_id)
                    return None
                if not self.asset_service:
                    raise RuntimeError("AssetService not initialized")
                lookup_bytes = self.asset_service.storage.get_object_bytes(lookup_object_path)
            return load_lookup_table_from_bytes(lookup_bytes)
        except Exception as e:
            self.logger.error("加载查找表失败 error={}", e)
            return None

    @staticmethod
    def _extract_lookup_paths(sample_meta: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        def get_value(meta: Dict[str, Any], *keys: str) -> Optional[str]:
            for key in keys:
                value = meta.get(key)
                if value:
                    return value
            return None

        lookup_local_path = get_value(sample_meta, "lookup_local_path", "lookupLocalPath")
        lookup_object_path = get_value(sample_meta, "lookup_object_path", "lookupObjectPath")

        fedo_meta = sample_meta.get("fedo_metadata") or sample_meta.get("fedoMetadata") or {}
        if not lookup_local_path:
            lookup_local_path = get_value(fedo_meta, "lookup_local_path", "lookupLocalPath")
        if not lookup_object_path:
            lookup_object_path = get_value(fedo_meta, "lookup_object_path", "lookupObjectPath")

        return lookup_local_path, lookup_object_path

    def _bbox_to_obb_vertices(self, data: Dict[str, Any]) -> np.ndarray:
        """
        Convert annotation data to OBB four corner coordinates.

        Args:
            data: Annotation data dict with x, y, width, height, rotation

        Returns:
            (4, 2) numpy array with four corner pixel coordinates
        """
        x = data.get('x', 0)
        y = data.get('y', 0)
        width = data.get('width', 0)
        height = data.get('height', 0)
        rotation = data.get('rotation', 0)

        # Create rectangle corners relative to center
        corners = np.array([
            [-width / 2, -height / 2],
            [width / 2, -height / 2],
            [width / 2, height / 2],
            [-width / 2, height / 2]
        ], dtype=np.float32)

        # Apply rotation
        if rotation != 0:
            angle_rad = np.deg2rad(rotation)
            cos_a = np.cos(angle_rad)
            sin_a = np.sin(angle_rad)
            rotation_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
            corners = corners @ rotation_matrix.T

        # Translate to center point
        corners[:, 0] += x
        corners[:, 1] += y

        return corners

    def _obb_vertices_to_bbox(self, vertices: np.ndarray) -> Dict[str, float]:
        """
        Convert OBB four corners to annotation data format.

        Args:
            vertices: (4, 2) numpy array with four corner pixel coordinates

        Returns:
            Dict with x, y, width, height, rotation
        """
        # Use cv2.minAreaRect to calculate minimum enclosing rectangle
        points = vertices.reshape(-1, 1, 2).astype(np.float32)
        rect = cv2.minAreaRect(points)

        # rect is a tuple: ((center_x, center_y), (width, height), angle)
        center, size, angle = rect

        # Ensure width >= height
        width, height = size
        if width < height:
            width, height = height, width
            angle += 90

        # Normalize angle to [-90, 90]
        while angle > 90:
            angle -= 180
        while angle < -90:
            angle += 180

        return {
            'x': float(center[0]),
            'y': float(center[1]),
            'width': float(width),
            'height': float(height),
            'rotation': float(angle)
        }

    def _generate_mapped_annotations(
            self,
            group_id: str,
            label_id: str,
            ann_type: AnnotationType,
            source_view: str,
            target_view: str,
            data: Dict[str, Any],
            context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """
        Generate mapped annotations for the target view.

        Uses the high-performance OBB mapping function to handle
        coordinate transformation with time-gap segmentation.

        Args:
            group_id: Group ID of the source annotation
            label_id: Label ID
            ann_type: Annotation type
            source_view: Source view name
            target_view: Target view name
            data: Annotation geometry data
            context: Annotation context

        Returns:
            List of generated annotation dicts
        """
        # Load lookup table
        lookup = self._load_lookup_table(context)
        if not lookup:
            self.logger.warning("无法加载查找表 sample_id={}", context.sample_id)
            raise ValueError("Cannot load lookup table")

        # Get source OBB vertices
        src_obb_vertices = self._bbox_to_obb_vertices(data)

        # Select correct LUT based on source and target views
        if source_view == VIEW_TIME_ENERGY and target_view == VIEW_L_OMEGAD:
            lut_src = lookup.lut_te  # (N, M, 2)
            lut_dst = lookup.lut_lw  # (N, M, 2)
        elif source_view == VIEW_L_OMEGAD and target_view == VIEW_TIME_ENERGY:
            lut_src = lookup.lut_lw  # (N, M, 2)
            lut_dst = lookup.lut_te  # (N, M, 2)
        else:
            self.logger.error("无效的 source_view source_view={}", source_view)
            raise ValueError("Invalid source_view")

        # Call high-performance OBB mapping function
        # Time-gap threshold: 50 (adjustable)
        time_gap_threshold = 50
        target_obb_vertices_list = map_obb_annotations(
            src_obb_vertices=src_obb_vertices,
            lut_src=lut_src,
            lut_dst=lut_dst,
            time_gap_threshold=time_gap_threshold,
            debug_output_dir=None,  # No debug output in production
        )

        # Convert OBB vertices to annotation format
        generated = []
        for target_vertices in target_obb_vertices_list:
            bbox_data = self._obb_vertices_to_bbox(target_vertices)

            generated_id = self.generate_id()
            generated.append({
                "id": generated_id,
                "label_id": label_id,
                "group_id": group_id,
                "lineage_id": generated_id,
                "type": AnnotationType.OBB.value if abs(bbox_data['rotation']) > 1e-6 else AnnotationType.RECT.value,
                "source": AnnotationSource.SYSTEM.value,
                "data": {
                    "x": bbox_data['x'],
                    "y": bbox_data['y'],
                    "width": bbox_data['width'],
                    "height": bbox_data['height'],
                    "rotation": bbox_data['rotation'],
                },
                "extra": {
                    "view": target_view,
                    "mapping_method": "fedo_obb_mapper",
                },
            })

        if not generated:
            raise ValueError("No boxes generated")

        return generated

    # ==================== Annotation Sync Methods ====================

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
        try:
            generated = self._generate_mapped_annotations(
                group_id=annotation_id,
                label_id=label_id,
                ann_type=ann_type,
                source_view=view,
                target_view=target_view,
                data=data,
                context=context,
            )

            self.logger.info(
                "FEDO 标注创建完成 annotation_id={} source_view={} target_view={} generated_count={}",
                annotation_id,
                view,
                target_view,
                len(generated),
            )

            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="create",
                generated=generated,
            )
        except Exception as e:
            self.logger.error("生成映射标注失败 error={}", e)
            return SyncResult(
                success=False,
                annotation_id=annotation_id,
                action="create",
                error=str(e),
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
        if not label_id or not ann_type:
            self.logger.warning(
                "FEDO 标注更新缺少 label_id 或 ann_type，无法重建映射标注 annotation_id={}",
                annotation_id,
            )
            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="update",
                generated=[{"_action": "regenerate_children"}],  # Signal frontend
            )

        # Generate mapped annotations (same logic as create)
        try:
            generated = self._generate_mapped_annotations(
                group_id=annotation_id,
                label_id=label_id,
                ann_type=ann_type,
                source_view=view,
                target_view=target_view,
                data=data,
                context=context,
            )

            self.logger.info(
                "FEDO 标注更新完成 annotation_id={} source_view={} target_view={} regenerated_count={}",
                annotation_id,
                view,
                target_view,
                len(generated),
            )

            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="update",
                generated=generated,
            )
        except Exception as e:
            self.logger.error("重建映射标注失败 error={}", e)
            return SyncResult(
                success=False,
                annotation_id=annotation_id,
                action="update",
                error=str(e),
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
        should also be deleted. Grouping is based on group_id.
        """
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="delete",
            generated=[{"_action": "delete_group", "group_id": annotation_id}],
        )
