"""Dual-view annotation sync handler.

Handles FEDO satellite data with dual-view annotation mapping.
When user annotates in one view, the system maps the annotation
to the corresponding region in the other view via lookup tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_ir import geometry_to_quad8_local, quad8_to_aabb_rect, quad8_to_obb_payload

from saki_api.modules.annotation.domain.ir_geometry_codec import normalize_geometry_payload, parse_geometry_dict
from saki_api.modules.annotation.extensions.data_formats.fedo.config import (
    get_fedo_config,
)
from saki_api.modules.annotation.extensions.data_formats.fedo.enum import FedoView
from saki_api.modules.annotation.extensions.data_formats.fedo.lookup import load_lookup_table_from_bytes
from saki_api.modules.annotation.extensions.data_formats.fedo.obb_mapper import map_obb_annotations
from saki_api.modules.annotation.extensions.sync.base import (
    AnnotationContext,
    BaseAnnotationSyncHandler,
    SyncResult,
)
from saki_api.modules.annotation.extensions.sync.registry import register_sync_handler
from saki_api.modules.shared.modeling.enums import AnnotationSource, AnnotationType, DatasetType

MAPPING_METHOD_FEDO = "fedo_obb_mapper"


@register_sync_handler
class DualViewSyncHandler(BaseAnnotationSyncHandler):
    """Sync handler for FEDO dual-view annotation mapping."""

    system_type = DatasetType.FEDO

    def __init__(self, session: Optional[AsyncSession] = None):
        """Initialize with database session for asset operations."""
        super().__init__(session)
        self._default_time_gap_threshold = self._load_default_time_gap_threshold()

    @staticmethod
    def _load_default_time_gap_threshold() -> int:
        """Load deployment-level default threshold once (env/config driven)."""
        threshold = int(get_fedo_config().mapping_time_gap_threshold)
        if threshold <= 0:
            raise ValueError(f"Invalid fedo.mapping_time_gap_threshold={threshold}, must be > 0")
        return threshold

    def _load_lookup_table(self, context: AnnotationContext):
        """Load lookup table from object storage (no disk)."""
        try:
            lookup_bytes = self._read_lookup_bytes(
                context.sample_meta or {},
                sample_id=context.sample_id,
            )
            if lookup_bytes is None:
                return None
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

    def _read_lookup_bytes(self, sample_meta: Dict[str, Any], *, sample_id: Optional[str] = None) -> Optional[bytes]:
        lookup_local_path, lookup_object_path = self._extract_lookup_paths(sample_meta)
        if lookup_local_path:
            path = Path(lookup_local_path)
            if path.exists():
                return path.read_bytes()

        if not lookup_object_path:
            if sample_id:
                self.logger.warning("样本缺少查找表路径 sample_id={}", sample_id)
            return None

        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")
        return self.asset_service.storage.get_object_bytes(lookup_object_path)

    @staticmethod
    def _select_lut_pair(
            lookup: Any,
            *,
            source_view: FedoView,
            target_view: FedoView,
    ) -> tuple[np.ndarray, np.ndarray]:
        if source_view == FedoView.TIME_ENERGY and target_view == FedoView.L_OMEGAD:
            return lookup.lut_te, lookup.lut_lw
        if source_view == FedoView.L_OMEGAD and target_view == FedoView.TIME_ENERGY:
            return lookup.lut_lw, lookup.lut_te
        raise ValueError(f"Invalid view mapping source={source_view} target={target_view}")

    @staticmethod
    def _resolve_source_view(
            attrs: Optional[Dict[str, Any]],
            *,
            default_view: Optional[FedoView] = None,
    ) -> FedoView:
        view = attrs.get("view") if attrs else None
        if view is not None:
            try:
                return FedoView.parse(str(view))
            except ValueError:
                pass
        if default_view is not None:
            return default_view
        raise ValueError(
            f"Invalid view: {view}. Must be '{FedoView.TIME_ENERGY.value}' or '{FedoView.L_OMEGAD.value}'"
        )

    @staticmethod
    def _target_view_for(source_view: FedoView) -> FedoView:
        if source_view == FedoView.TIME_ENERGY:
            return FedoView.L_OMEGAD
        if source_view == FedoView.L_OMEGAD:
            return FedoView.TIME_ENERGY
        raise ValueError(f"Invalid source view: {source_view}")

    @staticmethod
    def _geometry_to_vertices(geometry: Dict[str, Any]) -> np.ndarray:
        """Convert Geometry ProtoJSON (rect/obb) into 4 OBB-like vertices."""
        quad8 = geometry_to_quad8_local(parse_geometry_dict(geometry))
        return np.asarray(quad8, dtype=np.float32).reshape(4, 2)

    @staticmethod
    def _obb_vertices_to_geometry(vertices: np.ndarray) -> Dict[str, Any]:
        """Convert mapped vertices into normalized OBB Geometry ProtoJSON."""

        points = np.asarray(vertices, dtype=np.float32).reshape(-1, 2)
        if points.shape != (4, 2):
            raise ValueError("mapped vertices must contain exactly 4 points")

        payload = quad8_to_obb_payload(points.reshape(-1).tolist(), fit_mode="strict_then_min_area")
        obb = payload.get("obb") if isinstance(payload, dict) else None
        if not isinstance(obb, dict):
            raise ValueError("mapped vertices cannot be fitted into OBB")

        _, normalized_geometry = normalize_geometry_payload(
            annotation_type=AnnotationType.OBB,
            geometry_payload={
                "obb": {
                    "cx": float(obb.get("cx", 0.0)),
                    "cy": float(obb.get("cy", 0.0)),
                    "width": float(obb.get("width", 0.0)),
                    "height": float(obb.get("height", 0.0)),
                    "angle_deg_ccw": float(obb.get("angle_deg_ccw", 0.0)),
                }
            },
            confidence=1.0,
            source=AnnotationSource.SYSTEM,
        )
        return normalized_geometry

    @staticmethod
    def _maybe_convert_to_rect(geometry: Dict[str, Any]) -> tuple[AnnotationType, Dict[str, Any]]:
        """Convert axis-aligned OBB to RECT for cleaner downstream display."""

        obb = geometry.get("obb")
        if not isinstance(obb, dict):
            return AnnotationType.RECT, geometry

        angle = float(obb.get("angle_deg_ccw", obb.get("angleDegCcw", 0.0)))
        if abs(angle) > 1e-6:
            return AnnotationType.OBB, geometry

        qbox = geometry_to_quad8_local(geometry)
        x, y, w, h = quad8_to_aabb_rect(qbox)
        return AnnotationType.RECT, {
            "rect": {
                "x": float(x),
                "y": float(y),
                "width": float(w),
                "height": float(h),
            }
        }

    def _generate_mapped_annotations(
            self,
            group_id: str,
            label_id: str,
            source_view: FedoView,
            target_view: FedoView,
            geometry: Dict[str, Any],
            context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """Generate mapped annotations for the target view."""
        # Load lookup table
        lookup = self._load_lookup_table(context)
        if not lookup:
            self.logger.warning("无法加载查找表 sample_id={}", context.sample_id)
            raise ValueError("Cannot load lookup table")

        # Get source OBB vertices
        src_obb_vertices = self._geometry_to_vertices(geometry)

        lut_src, lut_dst = self._select_lut_pair(
            lookup,
            source_view=source_view,
            target_view=target_view,
        )

        # Call high-performance OBB mapping function
        target_obb_vertices_list = map_obb_annotations(
            src_obb_vertices=src_obb_vertices,
            lut_src=lut_src,
            lut_dst=lut_dst,
            time_gap_threshold=self._default_time_gap_threshold,
            debug_output_dir=None,  # No debug output in production
        )

        # Convert OBB vertices to geometry format
        generated = []
        for target_vertices in target_obb_vertices_list:
            mapped_geometry = self._obb_vertices_to_geometry(target_vertices)
            mapped_type, mapped_geometry = self._maybe_convert_to_rect(mapped_geometry)

            generated.append(
                self._build_generated_annotation(
                    group_id=group_id,
                    label_id=label_id,
                    mapped_type=mapped_type,
                    mapped_geometry=mapped_geometry,
                    target_view=target_view,
                )
            )

        if not generated:
            raise ValueError("No boxes generated")

        return generated

    def _build_generated_annotation(
            self,
            *,
            group_id: str,
            label_id: str,
            mapped_type: AnnotationType,
            mapped_geometry: Dict[str, Any],
            target_view: FedoView,
    ) -> Dict[str, Any]:
        generated_id = self.generate_id()
        return {
            "id": generated_id,
            "label_id": label_id,
            "group_id": group_id,
            "lineage_id": generated_id,
            "type": mapped_type.value,
            "source": AnnotationSource.SYSTEM.value,
            "geometry": mapped_geometry,
            "attrs": {
                "view": target_view.value,
                "mapping_method": MAPPING_METHOD_FEDO,
            },
        }

    def _build_mapping_sync_result(
            self,
            *,
            action: str,
            annotation_id: str,
            label_id: str,
            source_view: FedoView,
            target_view: FedoView,
            geometry: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        try:
            generated = self._generate_mapped_annotations(
                group_id=annotation_id,
                label_id=label_id,
                source_view=source_view,
                target_view=target_view,
                geometry=geometry,
                context=context,
            )
            action_text = "创建" if action == "create" else "更新"
            count_key = "generated_count" if action == "create" else "regenerated_count"
            self.logger.info(
                "FEDO 标注{}完成 annotation_id={} source_view={} target_view={} {}={}",
                action_text,
                annotation_id,
                source_view.value,
                target_view.value,
                count_key,
                len(generated),
            )
            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action=action,
                generated=generated,
            )
        except Exception as e:
            error_text = "生成映射标注失败" if action == "create" else "重建映射标注失败"
            self.logger.error("{} error={}", error_text, e)
            return SyncResult(
                success=False,
                annotation_id=annotation_id,
                action=action,
                error=str(e),
            )

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
        """Handle FEDO annotation creation with dual-view mapping."""
        _ = ann_type  # keep signature aligned with handler contract
        try:
            view = self._resolve_source_view(attrs, default_view=None)
            target_view = self._target_view_for(view)
        except ValueError as e:
            return SyncResult(
                success=False,
                annotation_id=annotation_id,
                action="create",
                error=str(e),
            )
        return self._build_mapping_sync_result(
            action="create",
            annotation_id=annotation_id,
            label_id=label_id,
            source_view=view,
            target_view=target_view,
            geometry=geometry,
            context=context,
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
        """Handle FEDO annotation update."""
        # If geometry is None, no geometry change, no need to regenerate
        if geometry is None:
            return SyncResult(
                success=True,
                annotation_id=annotation_id,
                action="update",
                generated=[],
            )

        view = self._resolve_source_view(attrs, default_view=FedoView.TIME_ENERGY)
        target_view = self._target_view_for(view)

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

        return self._build_mapping_sync_result(
            action="update",
            annotation_id=annotation_id,
            label_id=label_id,
            source_view=view,
            target_view=target_view,
            geometry=geometry,
            context=context,
        )

    def on_annotation_delete(
            self,
            annotation_id: str,
            attrs: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """Handle FEDO annotation deletion."""
        return SyncResult(
            success=True,
            annotation_id=annotation_id,
            action="delete",
            generated=[{"_action": "delete_group", "group_id": annotation_id}],
        )
