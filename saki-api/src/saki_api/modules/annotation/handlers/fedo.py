"""
FEDO annotation system handler.
Handles satellite FEDO (electron flux) data annotation with dual-view mapping.

This handler provides:
- FEDO text file upload and processing (parsing, physics, visualization)
- Generated image asset management via object storage
- Dual-view annotation sync with automatic mapping between views
- Linked annotation management (manual → auto-generated)
"""

import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.enums import DatasetType, AnnotationType, AnnotationSource
from saki_api.modules.annotation.base import (
    AnnotationSystemHandler,
    AnnotationContext,
    EventType,
    ProcessingStage,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    SyncResult,
    UploadContext,
)
from saki_api.modules.annotation.registry import register_handler
# FEDO config + parser
from saki_api.modules.annotation.satellite_fedo.config import FedoConfig, get_fedo_config
from saki_api.modules.annotation.satellite_fedo.lookup import (
    load_lookup_table_from_bytes,
    LookupTable,
)
from saki_api.modules.annotation.satellite_fedo.obb_mapper import map_obb_annotations
from saki_api.modules.annotation.satellite_fedo.parser import load_fedo_data_from_bytes
# FEDO data processing utilities (in satellite_fedo submodule)
from saki_api.modules.annotation.satellite_fedo.processor import FedoProcessor, FedoData

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
    
    Asset Management:
    - Raw text file is stored as asset (role: raw_text)
    - Generated visualization images are stored as assets (roles: time_energy_image, l_omegad_image)
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

    def _update_progress(
            self,
            progress_callback: Optional[ProgressCallback],
            progress: Optional[ProgressInfo],
            current: int,
            message: str,
            stage: str,
    ) -> None:
        if not progress_callback or not progress:
            return
        progress.update(current, message, stage)
        progress_callback(EventType.PROCESS_PROGRESS, progress)

    async def _upload_raw_asset(self, file: UploadFile) -> "AssetRead":
        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")
        return await self.asset_service.upload_file(
            file,
            meta_info={"generated": False, "type": "fedo_raw"}
        )

    async def _read_file_content(self, file: UploadFile) -> bytes:
        await file.seek(0)
        return await file.read()

    def _get_fedo_config(self, context: UploadContext) -> FedoConfig:
        overrides: Dict[str, Any] = {}
        if isinstance(context.config.get("fedo"), dict):
            overrides.update(context.config["fedo"])
        if isinstance(context.config.get("visualization"), dict):
            overrides.update(context.config["visualization"])
        return get_fedo_config(overrides)

    def _process_file_with_processor(
            self,
            file_content: bytes,
            fedo_config: FedoConfig,
    ) -> FedoData:
        processor = self._get_processor("in_memory")
        df, e_centers, e_cols = load_fedo_data_from_bytes(file_content)
        return processor.process_data(
            df=df,
            e_centers=e_centers,
            e_cols=e_cols,
            config=fedo_config,
        )

    async def _upload_generated_bytes(
            self,
            content: bytes,
            filename: str,
            meta_info: Dict[str, Any],
            content_type: Optional[str] = None,
    ) -> "AssetRead":
        if not self.asset_service:
            raise RuntimeError("AssetService not initialized")

        file_obj = UploadFile(
            filename=filename,
            file=io.BytesIO(content),
            headers={"content-type": content_type} if content_type else None
        )

        return await self.asset_service.upload_file(file_obj, meta_info=meta_info)

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

    # ==================== Upload & Processing ====================

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
        """Load lookup table from object storage (no disk)."""
        try:
            meta = context.sample_meta or {}
            lookup_object_path = meta.get('lookup_object_path')

            if not lookup_object_path:
                self.logger.warning(f"No lookup_object_path in sample_meta for {context.sample_id}")
                return None

            if not self.asset_service:
                raise RuntimeError("AssetService not initialized")

            lookup_bytes = self.asset_service.storage.get_object_bytes(lookup_object_path)
            return load_lookup_table_from_bytes(lookup_bytes)
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

    def _bbox_to_obb_vertices(self, data: Dict[str, Any]) -> np.ndarray:
        """
        从标注数据转换为 OBB 四个顶点坐标。
        
        Args:
            data: 标注数据字典，包含 x, y, width, height, rotation
        
        Returns:
            (4, 2) numpy 数组，包含四个顶点的像素坐标
        """
        x = data.get('x', 0)
        y = data.get('y', 0)
        width = data.get('width', 0)
        height = data.get('height', 0)
        rotation = data.get('rotation', 0)

        # 创建矩形的四个角点（相对于中心点）
        corners = np.array([
            [-width / 2, -height / 2],
            [width / 2, -height / 2],
            [width / 2, height / 2],
            [-width / 2, height / 2]
        ], dtype=np.float32)

        # 应用旋转
        if rotation != 0:
            angle_rad = np.deg2rad(rotation)
            cos_a = np.cos(angle_rad)
            sin_a = np.sin(angle_rad)
            rotation_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
            corners = corners @ rotation_matrix.T

        # 平移到中心点
        corners[:, 0] += x
        corners[:, 1] += y

        return corners

    def _obb_vertices_to_bbox(self, vertices: np.ndarray) -> Dict[str, float]:
        """
        从 OBB 四个顶点转换为标注数据格式。
        
        Args:
            vertices: (4, 2) numpy 数组，包含四个顶点的像素坐标
        
        Returns:
            包含 x, y, width, height, rotation 的字典
        """
        # 使用 cv2.minAreaRect 计算最小外接矩形
        # 输入需要是 shape 为 (N, 1, 2) 的数组
        points = vertices.reshape(-1, 1, 2).astype(np.float32)
        rect = cv2.minAreaRect(points)

        # rect 是一个元组: ((center_x, center_y), (width, height), angle)
        # 注意：cv2.minAreaRect 返回的角度范围是 [-90, 0)，单位是度
        center, size, angle = rect

        # 确保宽度 >= 高度（cv2.minAreaRect 可能返回 width < height）
        width, height = size
        if width < height:
            width, height = height, width
            angle += 90

        # 将角度归一化到 [-90, 90] 范围
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
            parent_id: str,
            label_id: str,
            ann_type: AnnotationType,
            source_view: str,
            target_view: str,
            data: Dict[str, Any],
            context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """
        使用新的高性能 OBB 映射函数生成目标视图的映射标注。
        
        实现流程：
        1. 加载 lookup table
        2. 从源标注数据转换为 OBB 四个顶点
        3. 根据源视图和目标视图选择正确的 LUT
        4. 调用 map_obb_annotations 进行映射（支持时间轴跳变分段）
        5. 将返回的 OBB 顶点转换为标注格式
        """
        # Load lookup table
        lookup = self._load_lookup_table(context)
        if not lookup:
            self.logger.warning(f"Cannot load lookup table for {context.sample_id}, using placeholder")
            raise ValueError("Cannot load lookup table")

        self.logger.warning(f"data: {data}")

        # 从标注数据获取源 OBB 四个顶点
        src_obb_vertices = self._bbox_to_obb_vertices(data)

        self.logger.warning(f"Source OBB vertices: {src_obb_vertices}")
        # 根据源视图和目标视图选择正确的 LUT
        if source_view == VIEW_TIME_ENERGY and target_view == VIEW_L_OMEGAD:
            lut_src = lookup.lut_te  # (N, M, 2)
            lut_dst = lookup.lut_lw  # (N, M, 2)
        elif source_view == VIEW_L_OMEGAD and target_view == VIEW_TIME_ENERGY:
            lut_src = lookup.lut_lw  # (N, M, 2)
            lut_dst = lookup.lut_te  # (N, M, 2)
        else:
            self.logger.error(f"Invalid source_view: {source_view}")
            raise ValueError("Invalid source_view")

        self.logger.warning(f"Source view: {source_view}")
        self.logger.warning(f"Target view: {target_view}")

        # 准备调试输出目录（如果可用）
        debug_output_dir = None
        try:
            from saki_api.core.config import settings
            meta = context.sample_meta
            lookup_url = meta.get('lookup_table_url')
            if lookup_url:
                # 从 lookup_url 解析出目录路径
                # URL format: /static/{dataset_id}/processed/{sample_id}/lookup.npz
                lookup_path = os.path.join(settings.UPLOAD_DIR, lookup_url.lstrip('/static/'))
                lookup_dir = os.path.dirname(lookup_path)
                # 在相同目录下创建 debug 子目录
                debug_output_dir = os.path.join(lookup_dir, 'debug')
        except Exception as e:
            self.logger.warning(f"Failed to setup debug output directory: {e}")

        # 调用高性能 OBB 映射函数
        # 默认时间轴跳变阈值为 50（可以根据需要调整）
        time_gap_threshold = 50
        target_obb_vertices_list = map_obb_annotations(
            src_obb_vertices=src_obb_vertices,
            lut_src=lut_src,
            lut_dst=lut_dst,
            time_gap_threshold=time_gap_threshold,
            debug_output_dir=debug_output_dir,
        )

        self.logger.warning(f"Target OBB vertices list: {target_obb_vertices_list}")

        # 将返回的 OBB 顶点列表转换为标注格式
        generated = []
        for target_vertices in target_obb_vertices_list:
            # 从 OBB 顶点转换为标注数据格式
            bbox_data = self._obb_vertices_to_bbox(target_vertices)

            generated_id = self.generate_id()
            generated.append({
                "id": generated_id,
                "label_id": label_id,
                "type": AnnotationType.OBB.value if abs(bbox_data['rotation']) > 1e-6 else AnnotationType.RECT.value,
                "source": AnnotationSource.FEDO_MAPPING.value,
                "data": {
                    "x": bbox_data['x'],
                    "y": bbox_data['y'],
                    "width": bbox_data['width'],
                    "height": bbox_data['height'],
                    "rotation": bbox_data['rotation'],
                },
                "extra": {
                    "parent_id": parent_id,
                    "view": target_view,
                    "mapping_method": "fedo_obb_mapper",
                },
            })

        if not generated:
            # Fallback to placeholder if no boxes generated
            raise ValueError("No boxes generated")

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
