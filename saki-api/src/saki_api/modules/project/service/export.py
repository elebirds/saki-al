from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_ir import (
    AnnotationRecord,
    AnnotationSource as IRAnnotationSource,
    ConversionContext,
    ConversionReport,
    DataBatchIR,
    LabelRecord,
    SampleRecord,
    get_format_profile,
    ir_to_coco,
    ir_to_dota_txt,
    ir_to_voc_xml,
    ir_to_yolo_obb_txt,
    ir_to_yolo_txt,
    parse_geometry,
)
from saki_ir.convert import build_batch, dict_to_struct

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.modules.annotation.contracts import AnnotationReadGateway
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.api.export import (
    FormatProfileRead,
    ProjectExportAssetRead,
    ProjectExportChunkFileRead,
    ProjectExportChunkRequest,
    ProjectExportChunkResponse,
    ProjectExportDatasetStat,
    ProjectExportResolveRequest,
    ProjectExportResolveResponse,
    ProjectIOCapabilitiesRead,
)
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.project.repo.commit import CommitRepository
from saki_api.modules.project.service.io_capability import IOCapabilityService
from saki_api.modules.project.service.label import LabelService
from saki_api.modules.project.service.project import ProjectService
from saki_api.modules.shared.modeling.enums import AnnotationSource as DBAnnotationSource, CommitSampleReviewState
from saki_api.modules.storage.domain.asset import Asset
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.storage.service.asset import AssetService


_SAMPLE_SCOPE = Literal["all", "labeled", "unlabeled"]


@dataclass(slots=True)
class _ResolveDatasetStats:
    sample_count: int = 0
    estimated_asset_bytes: int = 0


@dataclass(slots=True)
class _SampleExportContext:
    root_prefix: str
    image_relative_path: str
    image_stem: str
    image_export_path: str
    width: int
    height: int


_DEFAULT_IMAGE_EXT = ".jpg"


class ExportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_service = ProjectService(session)
        self.asset_service = AssetService(session)
        self.label_service = LabelService(session)
        self.annotation_gateway = AnnotationReadGateway(session)
        self.branch_repo = BranchRepository(session)
        self.commit_repo = CommitRepository(session)

    async def get_io_capabilities(self, *, project_id: uuid.UUID) -> ProjectIOCapabilitiesRead:
        project = await self.project_service.get_by_id_or_raise(project_id)
        enabled_annotation_types = [
            item.value if hasattr(item, "value") else str(item)
            for item in (project.enabled_annotation_types or [])
        ]

        export_profiles = IOCapabilityService.build_profiles(
            enabled_annotation_types=enabled_annotation_types,
            mode="export",
        )
        import_profiles = IOCapabilityService.build_profiles(
            enabled_annotation_types=enabled_annotation_types,
            mode="import",
        )

        return ProjectIOCapabilitiesRead(
            enabled_annotation_types=enabled_annotation_types,
            export_profiles=[
                FormatProfileRead(
                    id=item.id,
                    family=item.family,
                    supports_import=item.supports_import,
                    supports_export=item.supports_export,
                    supported_annotation_types=list(item.supported_annotation_types),
                    yolo_label_options=list(item.yolo_label_options),
                    available=item.available,
                    reason=item.reason,
                )
                for item in export_profiles
            ],
            import_profiles=[
                FormatProfileRead(
                    id=item.id,
                    family=item.family,
                    supports_import=item.supports_import,
                    supports_export=item.supports_export,
                    supported_annotation_types=list(item.supported_annotation_types),
                    yolo_label_options=list(item.yolo_label_options),
                    available=item.available,
                    reason=item.reason,
                )
                for item in import_profiles
            ],
        )

    async def resolve_export(
        self,
        *,
        project_id: uuid.UUID,
        payload: ProjectExportResolveRequest,
    ) -> ProjectExportResolveResponse:
        project = await self.project_service.get_by_id_or_raise(project_id)
        project_enabled_types = {
            item.value if hasattr(item, "value") else str(item)
            for item in (project.enabled_annotation_types or [])
        }
        dataset_ids = await self._resolve_dataset_ids(project_id=project_id, dataset_ids=payload.dataset_ids)
        commit_id = await self._resolve_commit_id(project_id=project_id, snapshot=payload.snapshot)
        self._validate_format_options(payload=payload)

        sample_stmt = self._build_sample_statement(
            dataset_ids=dataset_ids,
            commit_id=commit_id,
            sample_scope=payload.sample_scope,
        ).order_by(Sample.id)
        sample_rows = list((await self.session.exec(sample_stmt)).all())
        samples = self._coerce_samples(sample_rows)

        stats_by_dataset: dict[uuid.UUID, _ResolveDatasetStats] = defaultdict(_ResolveDatasetStats)
        for dataset_id in dataset_ids:
            _ = stats_by_dataset[dataset_id]
        for sample in samples:
            stats_by_dataset[sample.dataset_id].sample_count += 1

        estimated_total_asset_bytes = 0
        if payload.include_assets and samples:
            dataset_asset_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
            for sample in samples:
                for asset_id in self._collect_sample_asset_ids(sample):
                    dataset_asset_ids[sample.dataset_id].add(asset_id)
            all_asset_ids = {asset_id for values in dataset_asset_ids.values() for asset_id in values}
            size_by_asset_id = await self._query_asset_sizes(all_asset_ids)
            for dataset_id, asset_ids in dataset_asset_ids.items():
                dataset_bytes = sum(size_by_asset_id.get(asset_id, 0) for asset_id in asset_ids)
                stats_by_dataset[dataset_id].estimated_asset_bytes = dataset_bytes
                estimated_total_asset_bytes += dataset_bytes

        annotation_type_counts = await self._count_annotation_types(
            commit_id=commit_id,
            dataset_ids=dataset_ids,
            sample_scope=payload.sample_scope,
        )
        profile = get_format_profile(payload.format_profile)
        supported_types = set(profile.supported_annotation_types)
        missing_policy_required_types = sorted(
            ann_type for ann_type in project_enabled_types if ann_type not in supported_types
        )
        incompatible_types = sorted(
            [ann_type for ann_type in annotation_type_counts.keys() if ann_type not in supported_types]
        )

        blocked = False
        block_reason: str | None = None
        suggestions: list[str] = []

        if missing_policy_required_types:
            blocked = True
            block_reason = "PROJECT_ANNOTATION_POLICY_INCOMPATIBLE"
            suggestions.append(
                "当前项目导出标注策略要求导出格式支持: "
                f"{', '.join(missing_policy_required_types)}。"
            )

        if incompatible_types:
            blocked = True
            if block_reason is None:
                block_reason = "FORMAT_INCOMPATIBLE"
            suggestions.append(
                f"当前导出格式不支持标注类型: {', '.join(incompatible_types)}，请切换为兼容格式。"
            )

        if payload.include_assets and estimated_total_asset_bytes > settings.EXPORT_FRONTEND_MAX_TOTAL_BYTES:
            blocked = True
            if block_reason is None:
                block_reason = "ASSET_SIZE_EXCEEDED"
            suggestions.extend(
                [
                    "导出体量超过前端流式阈值，请减少数据集数量后重试。",
                    "可改为仅导出标注，或按数据集拆分导出。",
                ]
            )

        dataset_stats = []
        for dataset_id in dataset_ids:
            stats = stats_by_dataset[dataset_id]
            dataset_stats.append(
                ProjectExportDatasetStat(
                    dataset_id=dataset_id,
                    sample_count=stats.sample_count,
                    estimated_asset_bytes=stats.estimated_asset_bytes,
                )
            )

        return ProjectExportResolveResponse(
            resolved_commit_id=commit_id,
            dataset_stats=dataset_stats,
            estimated_total_asset_bytes=estimated_total_asset_bytes,
            format_compatibility=(
                "incompatible"
                if (incompatible_types or missing_policy_required_types)
                else "ok"
            ),
            blocked=blocked,
            block_reason=block_reason,
            suggestions=suggestions,
            annotation_type_counts=annotation_type_counts,
        )

    async def get_export_chunk(
        self,
        *,
        project_id: uuid.UUID,
        payload: ProjectExportChunkRequest,
    ) -> ProjectExportChunkResponse:
        dataset_ids = await self._resolve_dataset_ids(project_id=project_id, dataset_ids=payload.dataset_ids)
        await self._ensure_commit_in_project(project_id=project_id, commit_id=payload.resolved_commit_id)
        _ = get_format_profile(payload.format_profile)

        offset = max(0, int(payload.cursor or 0))
        sample_stmt = self._build_sample_statement(
            dataset_ids=dataset_ids,
            commit_id=payload.resolved_commit_id,
            sample_scope=payload.sample_scope,
        ).order_by(Sample.id)
        sample_rows = list(
            (
                await self.session.exec(
                    sample_stmt.offset(offset).limit(payload.limit)
                )
            ).all()
        )
        samples = self._coerce_samples(sample_rows)
        sample_ids = [sample.id for sample in samples]
        dataset_name_by_id = await self._load_dataset_name_map(dataset_ids)

        annotations_by_sample = (
            await self.annotation_gateway.get_annotations_by_commit_and_samples(
                commit_id=payload.resolved_commit_id,
                sample_ids=sample_ids,
            )
            if sample_ids
            else {}
        )
        sample_assets = (
            await self._build_assets_by_sample(samples)
            if payload.include_assets
            else {}
        )
        primary_assets_by_sample = await self._query_primary_assets_by_sample(samples)
        labels = await self.label_service.get_by_project(project_id)
        yolo_class_to_index = self._build_yolo_class_index(labels)
        label_records = self._to_ir_labels(labels)

        files: list[ProjectExportChunkFileRead] = []
        issues: list[str] = []
        for sample in samples:
            sample_assets_for_write = sample_assets.get(sample.id, [])
            root_prefix = self._build_dataset_root_prefix(
                dataset_id=sample.dataset_id,
                dataset_name=dataset_name_by_id.get(sample.dataset_id),
                bundle_layout=payload.bundle_layout,
                selected_dataset_count=len(dataset_ids),
            )
            sample_ctx = self._build_sample_export_context(
                sample=sample,
                root_prefix=root_prefix,
                assets=sample_assets_for_write,
                primary_asset=primary_assets_by_sample.get(sample.id),
                format_profile=payload.format_profile,
            )
            if payload.format_profile != "coco":
                files.extend(
                    self._build_annotation_files_for_sample(
                        sample=sample,
                        annotations=annotations_by_sample.get(sample.id, []),
                        sample_ctx=sample_ctx,
                        label_records=label_records,
                        class_to_index=yolo_class_to_index,
                        format_profile=payload.format_profile,
                        issues=issues,
                        dataset_name=dataset_name_by_id.get(sample.dataset_id),
                    )
                )
            if payload.include_assets:
                files.extend(
                    self._build_asset_files_for_sample(
                        sample=sample,
                        assets=sample_assets_for_write,
                        sample_ctx=sample_ctx,
                    )
                )

        next_cursor = offset + len(samples) if len(samples) >= payload.limit else None
        if next_cursor is None:
            final_files, final_issues = await self._build_final_export_files(
                commit_id=payload.resolved_commit_id,
                dataset_ids=dataset_ids,
                sample_scope=payload.sample_scope,
                format_profile=payload.format_profile,
                bundle_layout=payload.bundle_layout,
                labels=labels,
                class_to_index=yolo_class_to_index,
                dataset_name_by_id=dataset_name_by_id,
            )
            files.extend(final_files)
            issues.extend(final_issues)

        return ProjectExportChunkResponse(
            next_cursor=next_cursor,
            sample_count=len(samples),
            files=files,
            issues=issues,
        )

    async def _load_dataset_name_map(self, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not dataset_ids:
            return {}
        rows = list(
            (
                await self.session.exec(
                    select(Dataset.id, Dataset.name).where(Dataset.id.in_(dataset_ids))
                )
            ).all()
        )
        result: dict[uuid.UUID, str] = {}
        for row in rows:
            if isinstance(row, tuple) and len(row) == 2:
                dataset_id, dataset_name = row
                result[dataset_id] = str(dataset_name or dataset_id)
                continue
            if hasattr(row, "_mapping"):
                mapping = getattr(row, "_mapping")
                dataset_id = mapping.get(Dataset.id) if hasattr(mapping, "get") else None
                dataset_name = mapping.get(Dataset.name) if hasattr(mapping, "get") else None
                if isinstance(dataset_id, uuid.UUID):
                    result[dataset_id] = str(dataset_name or dataset_id)
        return result

    @staticmethod
    def _build_yolo_class_index(labels: list) -> dict[str, int]:
        class_to_index: dict[str, int] = {}
        for label in labels:
            name = str(label.name or label.id).strip() or str(label.id)
            if name in class_to_index:
                continue
            class_to_index[name] = len(class_to_index)
        return class_to_index

    @staticmethod
    def _sanitize_path_segment(value: str) -> str:
        cleaned = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", str(value or "").strip())
        return cleaned or "unknown"

    @classmethod
    def _normalize_relative_path(cls, value: str) -> str:
        raw = str(value or "").replace("\\", "/").strip()
        trimmed = re.sub(r"^\./", "", raw)
        trimmed = re.sub(r"^/+", "", trimmed)
        parts = []
        for part in trimmed.split("/"):
            token = part.strip()
            if not token or token in {".", ".."}:
                continue
            parts.append(cls._sanitize_path_segment(token))
        return "/".join(parts)

    @staticmethod
    def _path_ext(path: str) -> str:
        idx = path.rfind(".")
        if idx <= 0 or idx == len(path) - 1:
            return ""
        return path[idx:].lower()

    @staticmethod
    def _strip_ext(path: str) -> str:
        idx = path.rfind(".")
        if idx <= 0:
            return path
        return path[:idx]

    @classmethod
    def _ensure_ext(cls, path: str, ext: str) -> str:
        if not ext:
            return path
        return path if cls._path_ext(path) else f"{path}{ext if ext.startswith('.') else f'.{ext}'}"

    @classmethod
    def _build_dataset_root_prefix(
        cls,
        *,
        dataset_id: uuid.UUID,
        dataset_name: str | None,
        bundle_layout: Literal["merged_zip", "per_dataset_zip"],
        selected_dataset_count: int,
    ) -> str:
        if bundle_layout == "merged_zip":
            return f"datasets/{cls._sanitize_path_segment(dataset_name or str(dataset_id))}/"
        if selected_dataset_count <= 1:
            return ""
        return f"datasets/{cls._sanitize_path_segment(dataset_name or str(dataset_id))}/"

    @staticmethod
    def _to_positive_int(value: object) -> int:
        try:
            number = int(float(value))  # noqa: PERF203
        except Exception:  # noqa: BLE001
            return 0
        return number if number > 0 else 0

    def _resolve_sample_image_size(
        self,
        *,
        sample: Sample,
        primary_asset_read: ProjectExportAssetRead | None,
        primary_asset: Asset | None,
    ) -> tuple[int, int]:
        sample_meta = dict(sample.meta_info or {})
        width = self._to_positive_int(sample_meta.get("width") or sample_meta.get("imageWidth"))
        height = self._to_positive_int(sample_meta.get("height") or sample_meta.get("imageHeight"))
        if width > 0 and height > 0:
            return width, height

        asset_meta = dict((primary_asset_read.meta_info if primary_asset_read else None) or {})
        if not asset_meta and primary_asset is not None:
            asset_meta = dict(primary_asset.meta_info or {})
        width = self._to_positive_int(asset_meta.get("width") or asset_meta.get("imageWidth"))
        height = self._to_positive_int(asset_meta.get("height") or asset_meta.get("imageHeight"))
        return width, height

    def _build_sample_export_context(
        self,
        *,
        sample: Sample,
        root_prefix: str,
        assets: list[ProjectExportAssetRead],
        primary_asset: Asset | None,
        format_profile: str = "coco",
    ) -> _SampleExportContext:
        primary_asset_read = next(
            (item for item in assets if item.asset_id == sample.primary_asset_id),
            None,
        )
        if primary_asset_read is None:
            primary_asset_read = next((item for item in assets if item.role == "primary"), None)

        preferred_raw = self._normalize_relative_path(sample.name or "")
        preferred = preferred_raw or str(sample.id)
        primary_ext = ""
        if primary_asset_read and primary_asset_read.filename:
            primary_ext = self._path_ext(primary_asset_read.filename)
        if not primary_ext and primary_asset and primary_asset.original_filename:
            primary_ext = self._path_ext(primary_asset.original_filename)
        if not primary_ext and primary_asset and primary_asset.extension:
            primary_ext = str(primary_asset.extension).lower()
        ext = self._path_ext(preferred) or primary_ext or _DEFAULT_IMAGE_EXT
        if not ext.startswith("."):
            ext = f".{ext}"

        base_with_ext = self._ensure_ext(preferred, ext)
        stem = self._strip_ext(base_with_ext)
        suffix = str(sample.id).replace("-", "")[:8]
        image_relative_path = f"{stem}__{suffix}{ext}"
        width, height = self._resolve_sample_image_size(
            sample=sample,
            primary_asset_read=primary_asset_read,
            primary_asset=primary_asset,
        )
        if format_profile == "dota":
            image_export_path = f"{root_prefix}train/images/{image_relative_path}"
        else:
            image_export_path = f"{root_prefix}images/train/{image_relative_path}"
        return _SampleExportContext(
            root_prefix=root_prefix,
            image_relative_path=image_relative_path,
            image_stem=self._strip_ext(image_relative_path),
            image_export_path=image_export_path,
            width=width,
            height=height,
        )

    @staticmethod
    def _format_issue(*, dataset_name: str | None, sample_id: uuid.UUID | None, message: str) -> str:
        dataset_prefix = f"[{dataset_name}] " if dataset_name else ""
        sample_prefix = f"sample={sample_id} " if sample_id else ""
        return f"{dataset_prefix}{sample_prefix}{message}".strip()

    def _to_ir_sample_record(self, *, sample: Sample, sample_ctx: _SampleExportContext) -> SampleRecord:
        sample_meta = dict(sample.meta_info or {})
        sample_meta["width"] = int(sample_ctx.width)
        sample_meta["height"] = int(sample_ctx.height)
        external = dict(sample_meta.get("external") or {})
        external["source"] = "saki_export"
        external["sample_key"] = str(sample.id)
        external["file_name"] = Path(sample_ctx.image_relative_path).name
        relpath = sample_ctx.image_export_path
        if sample_ctx.root_prefix and relpath.startswith(sample_ctx.root_prefix):
            relpath = relpath[len(sample_ctx.root_prefix) :]
        external["relpath"] = relpath
        sample_meta["external"] = external

        record = SampleRecord(
            id=str(sample.id),
            width=int(sample_ctx.width),
            height=int(sample_ctx.height),
        )
        record.meta.CopyFrom(dict_to_struct(sample_meta))
        return record

    @staticmethod
    def _map_annotation_source(source: DBAnnotationSource) -> IRAnnotationSource:
        if source == DBAnnotationSource.MANUAL:
            return IRAnnotationSource.ANNOTATION_SOURCE_MANUAL
        if source == DBAnnotationSource.MODEL:
            return IRAnnotationSource.ANNOTATION_SOURCE_MODEL
        if source == DBAnnotationSource.CONFIRMED_MODEL:
            return IRAnnotationSource.ANNOTATION_SOURCE_CONFIRMED_MODEL
        if source == DBAnnotationSource.SYSTEM:
            return IRAnnotationSource.ANNOTATION_SOURCE_SYSTEM
        if source == DBAnnotationSource.IMPORTED:
            return IRAnnotationSource.ANNOTATION_SOURCE_IMPORTED
        return IRAnnotationSource.ANNOTATION_SOURCE_UNSPECIFIED

    def _to_ir_annotations(
        self,
        *,
        sample: Sample,
        annotations: list[Annotation],
        dataset_name: str | None,
    ) -> tuple[list[AnnotationRecord], list[str]]:
        records: list[AnnotationRecord] = []
        issues: list[str] = []
        for annotation in annotations:
            try:
                geometry = parse_geometry(dict(annotation.geometry or {}))
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    self._format_issue(
                        dataset_name=dataset_name,
                        sample_id=sample.id,
                        message=f"annotation={annotation.id} geometry parse failed: {exc}",
                    )
                )
                continue
            if geometry.WhichOneof("shape") is None:
                issues.append(
                    self._format_issue(
                        dataset_name=dataset_name,
                        sample_id=sample.id,
                        message=f"annotation={annotation.id} missing geometry shape",
                    )
                )
                continue
            ir_ann = AnnotationRecord(
                id=str(annotation.id),
                sample_id=str(sample.id),
                label_id=str(annotation.label_id),
                geometry=geometry,
                source=self._map_annotation_source(annotation.source),
                confidence=float(annotation.confidence),
            )
            attrs = dict(annotation.attrs or {})
            if attrs:
                ir_ann.attrs.CopyFrom(dict_to_struct(attrs))
            records.append(ir_ann)
        return records, issues

    @staticmethod
    def _to_ir_labels(labels: list) -> list[LabelRecord]:
        return [
            LabelRecord(
                id=str(label.id),
                name=str(label.name or label.id),
                color=str(label.color or ""),
            )
            for label in labels
        ]

    @staticmethod
    def _build_conversion_context(format_profile: str) -> ConversionContext:
        if format_profile == "yolo_obb":
            return ConversionContext(
                strict=False,
                include_external_ref=True,
                emit_labels=True,
                naming="keep_external",
                yolo_is_normalized=True,
                yolo_label_format="obb_rbox",
                yolo_obb_angle_unit="deg",
                yolo_float_precision=6,
            )
        if format_profile == "yolo":
            return ConversionContext(
                strict=False,
                include_external_ref=True,
                emit_labels=True,
                naming="keep_external",
                yolo_is_normalized=True,
                yolo_label_format="det",
                yolo_float_precision=6,
            )
        return ConversionContext(
            strict=False,
            include_external_ref=True,
            emit_labels=True,
            naming="keep_external",
        )

    def _collect_conversion_report_issues(
        self,
        *,
        report: ConversionReport,
        dataset_name: str | None,
        sample_id: uuid.UUID | None,
    ) -> list[str]:
        issues: list[str] = []
        for message in report.errors:
            issues.append(self._format_issue(dataset_name=dataset_name, sample_id=sample_id, message=message))
        for message in report.warnings:
            issues.append(self._format_issue(dataset_name=dataset_name, sample_id=sample_id, message=message))
        return issues

    def _build_annotation_files_for_sample(
        self,
        *,
        sample: Sample,
        annotations: list[Annotation],
        sample_ctx: _SampleExportContext,
        label_records: list[LabelRecord],
        class_to_index: dict[str, int],
        format_profile: str,
        issues: list[str],
        dataset_name: str | None,
    ) -> list[ProjectExportChunkFileRead]:
        sample_record = self._to_ir_sample_record(sample=sample, sample_ctx=sample_ctx)
        ann_records, parse_issues = self._to_ir_annotations(
            sample=sample,
            annotations=annotations,
            dataset_name=dataset_name,
        )
        issues.extend(parse_issues)
        batch = build_batch(label_records, [sample_record], ann_records)

        report = ConversionReport()
        context = self._build_conversion_context(format_profile)
        if format_profile == "voc":
            content = ir_to_voc_xml(batch, ctx=context, report=report)
            issues.extend(
                self._collect_conversion_report_issues(
                    report=report,
                    dataset_name=dataset_name,
                    sample_id=sample.id,
                )
            )
            return [
                ProjectExportChunkFileRead(
                    dataset_id=sample.dataset_id,
                    sample_id=sample.id,
                    path=f"{sample_ctx.root_prefix}Annotations/{sample_ctx.image_stem}.xml",
                    source_type="text",
                    text_content=content or "",
                )
            ]

        if format_profile == "yolo":
            content = ir_to_yolo_txt(
                batch,
                image_w=int(sample_ctx.width),
                image_h=int(sample_ctx.height),
                class_to_index=class_to_index,
                ctx=context,
                report=report,
            )
            issues.extend(
                self._collect_conversion_report_issues(
                    report=report,
                    dataset_name=dataset_name,
                    sample_id=sample.id,
                )
            )
            return [
                ProjectExportChunkFileRead(
                    dataset_id=sample.dataset_id,
                    sample_id=sample.id,
                    path=f"{sample_ctx.root_prefix}labels/train/{sample_ctx.image_stem}.txt",
                    source_type="text",
                    text_content=f"{content}\n" if content else "",
                )
            ]

        if format_profile == "dota":
            content = ir_to_dota_txt(batch, ctx=context, report=report)
            issues.extend(
                self._collect_conversion_report_issues(
                    report=report,
                    dataset_name=dataset_name,
                    sample_id=sample.id,
                )
            )
            return [
                ProjectExportChunkFileRead(
                    dataset_id=sample.dataset_id,
                    sample_id=sample.id,
                    path=f"{sample_ctx.root_prefix}train/labelTxt/{sample_ctx.image_stem}.txt",
                    source_type="text",
                    text_content=f"{content}\n" if content else "",
                )
            ]

        content = ir_to_yolo_obb_txt(
            batch,
            image_w=int(sample_ctx.width),
            image_h=int(sample_ctx.height),
            class_to_index=class_to_index,
            fmt="rbox",
            angle_unit="deg",
            ctx=context,
            report=report,
        )
        issues.extend(
            self._collect_conversion_report_issues(
                report=report,
                dataset_name=dataset_name,
                sample_id=sample.id,
            )
        )
        return [
            ProjectExportChunkFileRead(
                dataset_id=sample.dataset_id,
                sample_id=sample.id,
                path=f"{sample_ctx.root_prefix}labels/train/{sample_ctx.image_stem}.txt",
                source_type="text",
                text_content=f"{content}\n" if content else "",
            )
        ]

    def _build_aux_asset_path(
        self,
        *,
        sample: Sample,
        sample_ctx: _SampleExportContext,
        asset: ProjectExportAssetRead,
    ) -> str:
        raw_name = self._sanitize_path_segment(Path(str(asset.filename or asset.asset_id)).name)
        ext = self._path_ext(raw_name)
        base = self._strip_ext(raw_name)
        role = self._sanitize_path_segment(asset.role)
        suffix = str(asset.asset_id).replace("-", "")[:8]
        name = f"{role}_{base}__{suffix}{ext}"
        return f"{sample_ctx.root_prefix}assets/{self._sanitize_path_segment(str(sample.id))}/{name}"

    def _build_asset_files_for_sample(
        self,
        *,
        sample: Sample,
        assets: list[ProjectExportAssetRead],
        sample_ctx: _SampleExportContext,
    ) -> list[ProjectExportChunkFileRead]:
        files: list[ProjectExportChunkFileRead] = []
        for asset in assets:
            if not asset.download_url:
                continue
            if asset.role == "primary":
                path = sample_ctx.image_export_path
            else:
                path = self._build_aux_asset_path(sample=sample, sample_ctx=sample_ctx, asset=asset)
            files.append(
                ProjectExportChunkFileRead(
                    dataset_id=sample.dataset_id,
                    sample_id=sample.id,
                    path=path,
                    source_type="url",
                    download_url=asset.download_url,
                    size=asset.size,
                    role=asset.role,
                )
            )
        return files

    async def _build_final_export_files(
        self,
        *,
        commit_id: uuid.UUID,
        dataset_ids: list[uuid.UUID],
        sample_scope: _SAMPLE_SCOPE,
        format_profile: str,
        bundle_layout: Literal["merged_zip", "per_dataset_zip"],
        labels: list,
        class_to_index: dict[str, int],
        dataset_name_by_id: dict[uuid.UUID, str],
    ) -> tuple[list[ProjectExportChunkFileRead], list[str]]:
        files: list[ProjectExportChunkFileRead] = []
        issues: list[str] = []
        if format_profile in {"voc", "coco"}:
            all_samples = await self._query_all_samples(
                commit_id=commit_id,
                dataset_ids=dataset_ids,
                sample_scope=sample_scope,
            )
            grouped_samples: dict[uuid.UUID, list[Sample]] = defaultdict(list)
            for sample in all_samples:
                grouped_samples[sample.dataset_id].append(sample)
            primary_assets_by_sample = await self._query_primary_assets_by_sample(all_samples)
        else:
            grouped_samples = defaultdict(list)
            primary_assets_by_sample = {}

        if format_profile == "voc":
            for dataset_id in dataset_ids:
                root_prefix = self._build_dataset_root_prefix(
                    dataset_id=dataset_id,
                    dataset_name=dataset_name_by_id.get(dataset_id),
                    bundle_layout=bundle_layout,
                    selected_dataset_count=len(dataset_ids),
                )
                split_keys: list[str] = []
                for sample in grouped_samples.get(dataset_id, []):
                    sample_ctx = self._build_sample_export_context(
                        sample=sample,
                        root_prefix=root_prefix,
                        assets=[],
                        primary_asset=primary_assets_by_sample.get(sample.id),
                    )
                    split_keys.append(sample_ctx.image_stem)
                files.append(
                    ProjectExportChunkFileRead(
                        dataset_id=dataset_id,
                        path=f"{root_prefix}ImageSets/Main/train.txt",
                        source_type="text",
                        text_content=f"{'\n'.join(split_keys)}\n" if split_keys else "",
                    )
                )
            return files, issues

        if format_profile in {"yolo", "yolo_obb"}:
            names_by_index = sorted(class_to_index.items(), key=lambda item: item[1])
            yaml_lines = [
                "path: .",
                "train: images/train",
                "names:",
            ]
            for name, index in names_by_index:
                yaml_lines.append(f"  {index}: {name}")
            yaml_content = f"{'\n'.join(yaml_lines)}\n"
            for dataset_id in dataset_ids:
                root_prefix = self._build_dataset_root_prefix(
                    dataset_id=dataset_id,
                    dataset_name=dataset_name_by_id.get(dataset_id),
                    bundle_layout=bundle_layout,
                    selected_dataset_count=len(dataset_ids),
                )
                files.append(
                    ProjectExportChunkFileRead(
                        dataset_id=dataset_id,
                        path=f"{root_prefix}data.yaml",
                        source_type="text",
                        text_content=yaml_content,
                    )
                )
            return files, issues

        if format_profile != "coco":
            return files, issues

        labels_ir = self._to_ir_labels(labels)
        all_sample_ids = [sample.id for samples in grouped_samples.values() for sample in samples]
        annotations_by_sample = (
            await self.annotation_gateway.get_annotations_by_commit_and_samples(
                commit_id=commit_id,
                sample_ids=all_sample_ids,
            )
            if all_sample_ids
            else {}
        )
        for dataset_id in dataset_ids:
            root_prefix = self._build_dataset_root_prefix(
                dataset_id=dataset_id,
                dataset_name=dataset_name_by_id.get(dataset_id),
                bundle_layout=bundle_layout,
                selected_dataset_count=len(dataset_ids),
            )
            dataset_samples = grouped_samples.get(dataset_id, [])
            sample_records: list[SampleRecord] = []
            ann_records: list[AnnotationRecord] = []
            for sample in dataset_samples:
                sample_ctx = self._build_sample_export_context(
                    sample=sample,
                    root_prefix="",
                    assets=[],
                    primary_asset=primary_assets_by_sample.get(sample.id),
                )
                sample_records.append(self._to_ir_sample_record(sample=sample, sample_ctx=sample_ctx))
                parsed_annotations, parse_issues = self._to_ir_annotations(
                    sample=sample,
                    annotations=annotations_by_sample.get(sample.id, []),
                    dataset_name=dataset_name_by_id.get(dataset_id),
                )
                ann_records.extend(parsed_annotations)
                issues.extend(parse_issues)
            batch: DataBatchIR = build_batch(labels_ir, sample_records, ann_records)
            report = ConversionReport()
            content = json.dumps(
                ir_to_coco(
                    batch,
                    ctx=self._build_conversion_context("coco"),
                    report=report,
                ),
                ensure_ascii=False,
                indent=2,
            ) + "\n"
            issues.extend(
                self._collect_conversion_report_issues(
                    report=report,
                    dataset_name=dataset_name_by_id.get(dataset_id),
                    sample_id=None,
                )
            )
            files.append(
                ProjectExportChunkFileRead(
                    dataset_id=dataset_id,
                    path=f"{root_prefix}annotations/instances.json",
                    source_type="text",
                    text_content=content,
                )
            )
        return files, issues

    async def _query_all_samples(
        self,
        *,
        commit_id: uuid.UUID,
        dataset_ids: list[uuid.UUID],
        sample_scope: _SAMPLE_SCOPE,
    ) -> list[Sample]:
        statement = self._build_sample_statement(
            dataset_ids=dataset_ids,
            commit_id=commit_id,
            sample_scope=sample_scope,
        ).order_by(Sample.id)
        rows = list((await self.session.exec(statement)).all())
        return self._coerce_samples(rows)

    async def _query_primary_assets_by_sample(self, samples: list[Sample]) -> dict[uuid.UUID, Asset]:
        primary_ids = {sample.primary_asset_id for sample in samples if sample.primary_asset_id is not None}
        if not primary_ids:
            return {}
        asset_rows = list(
            (await self.session.exec(select(Asset).where(Asset.id.in_(primary_ids)))).all()
        )
        assets = self._coerce_assets(asset_rows)
        by_id = {asset.id: asset for asset in assets}
        result: dict[uuid.UUID, Asset] = {}
        for sample in samples:
            if sample.primary_asset_id is None:
                continue
            asset = by_id.get(sample.primary_asset_id)
            if asset is not None:
                result[sample.id] = asset
        return result

    async def _resolve_dataset_ids(self, *, project_id: uuid.UUID, dataset_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        linked_dataset_ids = list(await self.project_service.repository.get_linked_dataset_ids(project_id))
        linked_dataset_set = set(linked_dataset_ids)
        selected = list(dict.fromkeys(dataset_ids or linked_dataset_ids))
        if not selected:
            raise BadRequestAppException("No linked datasets available for export")
        illegal_ids = [dataset_id for dataset_id in selected if dataset_id not in linked_dataset_set]
        if illegal_ids:
            raise BadRequestAppException(f"Dataset is not linked to project: {illegal_ids[0]}")
        return selected

    async def _resolve_commit_id(self, *, project_id: uuid.UUID, snapshot) -> uuid.UUID:
        if snapshot.type == "branch_head":
            branch = await self.branch_repo.get_by_name(project_id, snapshot.branch_name)
            if not branch:
                raise NotFoundAppException(f"Branch '{snapshot.branch_name}' not found in project")
            if branch.head_commit_id is None:
                raise BadRequestAppException(f"Branch '{snapshot.branch_name}' has no head commit")
            return branch.head_commit_id
        await self._ensure_commit_in_project(project_id=project_id, commit_id=snapshot.commit_id)
        return snapshot.commit_id

    async def _ensure_commit_in_project(self, *, project_id: uuid.UUID, commit_id: uuid.UUID) -> None:
        commit = await self.commit_repo.get_by_id(commit_id)
        if not commit or commit.project_id != project_id:
            raise BadRequestAppException("Commit not found in project")

    @staticmethod
    def _validate_format_options(*, payload: ProjectExportResolveRequest) -> None:
        _ = get_format_profile(payload.format_profile)

    def _sample_id_subquery(
        self,
        *,
        dataset_ids: list[uuid.UUID],
        commit_id: uuid.UUID,
        sample_scope: _SAMPLE_SCOPE,
    ):
        sample_stmt = select(Sample.id).where(Sample.dataset_id.in_(dataset_ids))
        labeled_subq = select(CommitSampleState.sample_id).where(
            CommitSampleState.commit_id == commit_id,
            CommitSampleState.state.in_(
                (
                    CommitSampleReviewState.LABELED,
                    CommitSampleReviewState.EMPTY_CONFIRMED,
                )
            ),
        ).distinct()
        if sample_scope == "labeled":
            sample_stmt = sample_stmt.where(Sample.id.in_(labeled_subq))
        elif sample_scope == "unlabeled":
            sample_stmt = sample_stmt.where(~Sample.id.in_(labeled_subq))
        return sample_stmt

    def _build_sample_statement(
        self,
        *,
        dataset_ids: list[uuid.UUID],
        commit_id: uuid.UUID,
        sample_scope: _SAMPLE_SCOPE,
    ):
        sample_ids = self._sample_id_subquery(
            dataset_ids=dataset_ids,
            commit_id=commit_id,
            sample_scope=sample_scope,
        )
        return select(Sample).where(Sample.id.in_(sample_ids))

    @staticmethod
    def _coerce_samples(rows: list) -> list[Sample]:
        samples: list[Sample] = []
        for row in rows:
            if isinstance(row, Sample):
                samples.append(row)
                continue
            if isinstance(row, tuple) and row:
                candidate = row[0]
                if isinstance(candidate, Sample):
                    samples.append(candidate)
                    continue
            if hasattr(row, "_mapping"):
                mapping = getattr(row, "_mapping")
                candidate = mapping.get(Sample) if hasattr(mapping, "get") else None
                if isinstance(candidate, Sample):
                    samples.append(candidate)
                    continue
            raise BadRequestAppException("Unexpected sample row shape in export query result")
        return samples

    async def _count_annotation_types(
        self,
        *,
        commit_id: uuid.UUID,
        dataset_ids: list[uuid.UUID],
        sample_scope: _SAMPLE_SCOPE,
    ) -> dict[str, int]:
        sample_ids = self._sample_id_subquery(
            dataset_ids=dataset_ids,
            commit_id=commit_id,
            sample_scope=sample_scope,
        )
        statement = (
            select(Annotation.type, func.count(Annotation.id))
            .join(CommitAnnotationMap, CommitAnnotationMap.annotation_id == Annotation.id)
            .where(
                CommitAnnotationMap.commit_id == commit_id,
                CommitAnnotationMap.sample_id.in_(sample_ids),
            )
            .group_by(Annotation.type)
        )
        rows = (await self.session.exec(statement)).all()
        result: dict[str, int] = {}
        for ann_type, count in rows:
            key = ann_type.value if hasattr(ann_type, "value") else str(ann_type)
            result[key] = int(count or 0)
        return result

    @staticmethod
    def _collect_sample_asset_ids(sample: Sample) -> set[uuid.UUID]:
        asset_ids: set[uuid.UUID] = set()
        if sample.primary_asset_id:
            asset_ids.add(sample.primary_asset_id)
        if isinstance(sample.asset_group, dict):
            for raw_value in sample.asset_group.values():
                try:
                    asset_ids.add(uuid.UUID(str(raw_value)))
                except Exception:  # noqa: BLE001
                    continue
        return asset_ids

    async def _query_asset_sizes(self, asset_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not asset_ids:
            return {}
        rows = list((await self.session.exec(select(Asset.id, Asset.size).where(Asset.id.in_(asset_ids)))).all())
        return {asset_id: int(size or 0) for asset_id, size in rows}

    async def _build_assets_by_sample(self, samples: list[Sample]) -> dict[uuid.UUID, list[ProjectExportAssetRead]]:
        sample_role_asset: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = {}
        all_asset_ids: set[uuid.UUID] = set()
        for sample in samples:
            role_entries: list[tuple[str, uuid.UUID]] = []
            seen: set[uuid.UUID] = set()
            if sample.primary_asset_id:
                seen.add(sample.primary_asset_id)
                role_entries.append(("primary", sample.primary_asset_id))
            if isinstance(sample.asset_group, dict):
                for role, raw_id in sample.asset_group.items():
                    try:
                        asset_id = uuid.UUID(str(raw_id))
                    except Exception:  # noqa: BLE001
                        continue
                    if asset_id in seen:
                        continue
                    seen.add(asset_id)
                    role_entries.append((str(role), asset_id))
            sample_role_asset[sample.id] = role_entries
            for _, asset_id in role_entries:
                all_asset_ids.add(asset_id)

        if not all_asset_ids:
            return {}

        asset_rows = list((await self.session.exec(select(Asset).where(Asset.id.in_(all_asset_ids)))).all())
        assets = self._coerce_assets(asset_rows)
        asset_by_id = {asset.id: asset for asset in assets}
        url_by_asset_id: dict[uuid.UUID, str] = {}
        for asset_id in all_asset_ids:
            if asset_id not in asset_by_id:
                continue
            url_by_asset_id[asset_id] = await self.asset_service.get_presigned_download_url(
                asset_id,
                expires_in_hours=settings.EXPORT_ASSET_URL_EXPIRE_HOURS,
            )

        result: dict[uuid.UUID, list[ProjectExportAssetRead]] = {}
        for sample_id, entries in sample_role_asset.items():
            sample_assets: list[ProjectExportAssetRead] = []
            for role, asset_id in entries:
                asset = asset_by_id.get(asset_id)
                url = url_by_asset_id.get(asset_id)
                if not asset or not url:
                    continue
                sample_assets.append(
                    ProjectExportAssetRead(
                        role=role,
                        asset_id=asset_id,
                        filename=asset.original_filename,
                        size=asset.size,
                        meta_info=dict(asset.meta_info or {}),
                        download_url=url,
                    )
                )
            result[sample_id] = sample_assets
        return result

    @staticmethod
    def _coerce_assets(rows: list) -> list[Asset]:
        assets: list[Asset] = []
        for row in rows:
            if isinstance(row, Asset):
                assets.append(row)
                continue
            if isinstance(row, tuple) and row:
                candidate = row[0]
                if isinstance(candidate, Asset):
                    assets.append(candidate)
                    continue
            if hasattr(row, "_mapping"):
                mapping = getattr(row, "_mapping")
                candidate = mapping.get(Asset) if hasattr(mapping, "get") else None
                if isinstance(candidate, Asset):
                    assets.append(candidate)
                    continue
            raise BadRequestAppException("Unexpected asset row shape in export query result")
        return assets
