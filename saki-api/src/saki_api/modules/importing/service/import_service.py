from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.datastructures import Headers

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, ForbiddenAppException, NotFoundAppException
from saki_api.infra.cache.redis import get_redis_client
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.annotation.contracts import AnnotationReadGateway
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.project.api.label import LabelCreate
from saki_api.modules.project.domain.annotation_policy import normalize_enabled_annotation_types
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.project.service.dataset import DatasetService
from saki_api.modules.project.service.annotation_bulk import AnnotationBulkService
from saki_api.modules.project.service.sample_bulk import SampleBulkService
from saki_api.modules.project.service.label import LabelService
from saki_api.modules.project.service.project import ProjectService
from saki_api.modules.project.service.sample import SampleService
from saki_api.modules.shared.modeling.enums import AnnotationType, DatasetType
from saki_api.modules.storage.api.dataset import DatasetCreate
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.storage.service.asset import AssetService
from saki_api.modules.importing.schema import (
    AssociatedDatasetMode,
    AssociatedManifestTarget,
    ConflictStrategy,
    ImportDryRunResponse,
    ImportTaskCreateResponse,
    ImportExecuteRequest,
    ImportFormat,
    ImportIssue,
)
from saki_api.modules.importing.service.task_service import TaskService
from saki_ir import ConversionContext, ConversionReport, load_coco_dataset, load_voc_dataset, load_yolo_dataset
from saki_ir.convert import split_batch, struct_to_dict


_MAX_ISSUES_PER_KIND = 200
_MAX_EXECUTION_ITEM_EVENTS = 2000
_PREVIEW_TOKEN_KEY = f"{settings.REDIS_KEY_PREFIX}:import:preview"
_IMPORT_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "saki.import.annotation.v1")
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


@dataclass(slots=True)
class PreparedAnnotation:
    sample_key: str
    label_name: str
    ann_type: str
    geometry: dict[str, Any]
    confidence: float
    attrs: dict[str, Any]
    lineage_seed: str

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_key": self.sample_key,
            "label_name": self.label_name,
            "ann_type": self.ann_type,
            "geometry": self.geometry,
            "confidence": self.confidence,
            "attrs": self.attrs,
            "lineage_seed": self.lineage_seed,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PreparedAnnotation":
        return cls(
            sample_key=str(payload.get("sample_key") or ""),
            label_name=str(payload.get("label_name") or ""),
            ann_type=str(payload.get("ann_type") or "rect"),
            geometry=dict(payload.get("geometry") or {}),
            confidence=float(payload.get("confidence") or 1.0),
            attrs=dict(payload.get("attrs") or {}),
            lineage_seed=str(payload.get("lineage_seed") or ""),
        )


@dataclass(slots=True)
class PreviewTokenPayload:
    token: str
    mode: str
    user_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    zip_asset_id: uuid.UUID
    manifest_asset_id: uuid.UUID
    params_hash: str
    created_at: datetime
    expires_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "mode": self.mode,
            "user_id": str(self.user_id),
            "resource_type": self.resource_type,
            "resource_id": str(self.resource_id),
            "zip_asset_id": str(self.zip_asset_id),
            "manifest_asset_id": str(self.manifest_asset_id),
            "params_hash": self.params_hash,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PreviewTokenPayload":
        return cls(
            token=str(payload["token"]),
            mode=str(payload["mode"]),
            user_id=uuid.UUID(str(payload["user_id"])),
            resource_type=str(payload["resource_type"]),
            resource_id=uuid.UUID(str(payload["resource_id"])),
            zip_asset_id=uuid.UUID(str(payload["zip_asset_id"])),
            manifest_asset_id=uuid.UUID(str(payload["manifest_asset_id"])),
            params_hash=str(payload["params_hash"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        )


class ImportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.dataset_service = DatasetService(session)
        self.sample_service = SampleService(session)
        self.sample_bulk_service = SampleBulkService(session)
        self.annotation_bulk_service = AnnotationBulkService(session)
        self.project_service = ProjectService(session)
        self.label_service = LabelService(session)
        self.asset_service = AssetService(session)
        self.task_service = TaskService(session)
        self.annotation_gateway = AnnotationReadGateway(session)
        self._last_scan_total_files = 0

    # ---------------------------------------------------------------------
    # Public dry-run APIs
    # ---------------------------------------------------------------------

    async def dry_run_dataset_images(
        self,
        *,
        user_id: uuid.UUID,
        dataset_id: uuid.UUID,
        zip_file: UploadFile,
    ) -> ImportDryRunResponse:
        dataset = await self.dataset_service.get_by_id_or_raise(dataset_id)
        self._ensure_dataset_type_classic(dataset.type)
        await self._validate_zip_upload(zip_file)

        zip_asset = await self.asset_service.upload_file(
            zip_file,
            meta_info={"temporary": True, "import_mode": "dataset_images"},
        )

        issues_warnings: list[ImportIssue] = []
        issues_errors: list[ImportIssue] = []

        await zip_file.seek(0)
        with zipfile.ZipFile(zip_file.file) as archive:
            image_paths = self._collect_zip_image_paths(
                archive,
                warnings=issues_warnings,
                errors=issues_errors,
            )

        allow_duplicate_names = bool(dataset.allow_duplicate_sample_names)
        if allow_duplicate_names:
            reuse_count = 0
            new_count = len(image_paths)
        else:
            sample_names = await self._list_dataset_sample_names(dataset_id)
            existing_names = set(sample_names)
            reuse_count = sum(1 for item in image_paths if item in existing_names)
            new_count = len(image_paths) - reuse_count

        summary = {
            "mode": "dataset_images",
            "dataset_id": str(dataset_id),
            "allow_duplicate_sample_names": allow_duplicate_names,
            "total_entries": len(image_paths),
            "new_samples": new_count,
            "reused_samples": reuse_count,
            "skipped_non_image": max(0, self._last_scan_total_files - len(image_paths)),
        }

        manifest = {
            "mode": "dataset_images",
            "dataset_id": str(dataset_id),
            "image_paths": image_paths,
            "summary": summary,
            "warnings": [item.model_dump(mode="json") for item in issues_warnings],
            "errors": [item.model_dump(mode="json") for item in issues_errors],
        }
        params = {
            "mode": "dataset_images",
            "dataset_id": str(dataset_id),
        }

        return await self._build_dry_run_response(
            user_id=user_id,
            mode="dataset_images",
            resource_type=ResourceType.DATASET.value,
            resource_id=dataset_id,
            zip_asset_id=zip_asset.id,
            manifest=manifest,
            params=params,
            summary=summary,
            warnings=issues_warnings,
            errors=issues_errors,
            planned_new_labels=[],
        )

    async def dry_run_project_annotations(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        branch_name: str,
        fmt: ImportFormat,
        zip_file: UploadFile,
    ) -> ImportDryRunResponse:
        await self._validate_zip_upload(zip_file)
        await self._ensure_project_dataset_context(
            user_id=user_id,
            project_id=project_id,
            dataset_id=dataset_id,
            branch_name=branch_name,
        )

        zip_asset = await self.asset_service.upload_file(
            zip_file,
            meta_info={"temporary": True, "import_mode": "project_annotations"},
        )

        warnings: list[ImportIssue] = []
        errors: list[ImportIssue] = []
        prepared_annotations: list[PreparedAnnotation]
        raw_labels: list[str]

        with tempfile.TemporaryDirectory(prefix="saki-import-dryrun-") as temp_dir:
            extract_root = Path(temp_dir)
            await zip_file.seek(0)
            with zipfile.ZipFile(zip_file.file) as archive:
                self._extract_zip_archive(archive, extract_root)
            prepared_annotations, raw_labels, report = self._parse_annotations_from_dir(extract_root, fmt)

        self._append_conversion_report(report, warnings, errors)
        enabled_types = await self._get_project_enabled_annotation_types(project_id)
        enabled_type_values = {item.value for item in enabled_types}
        unsupported_type_counts = self._count_unsupported_annotation_types(
            prepared_annotations=prepared_annotations,
            enabled_type_values=enabled_type_values,
        )
        self._append_unsupported_type_issues(
            errors=errors,
            unsupported_type_counts=unsupported_type_counts,
            enabled_type_values=enabled_type_values,
        )

        sample_rows = await self._list_dataset_sample_rows(dataset_id)
        sample_lookup, basename_lookup = self._build_sample_lookup(sample_rows)

        matched_annotations = 0
        skipped_annotations = 0
        matched_sample_ids: set[uuid.UUID] = set()

        for ann in prepared_annotations:
            sample_id, via_basename = self._resolve_sample_id(
                ann.sample_key,
                sample_lookup,
                basename_lookup,
            )
            if sample_id is None:
                skipped_annotations += 1
                self._append_issue(
                    errors,
                    ImportIssue(
                        code="SAMPLE_NOT_FOUND",
                        message=f"sample key not found in dataset: {ann.sample_key}",
                        path=ann.sample_key,
                    ),
                )
                continue

            matched_annotations += 1
            matched_sample_ids.add(sample_id)
            if via_basename:
                self._append_issue(
                    warnings,
                    ImportIssue(
                        code="SAMPLE_MATCH_BY_BASENAME",
                        message=f"sample matched by basename fallback: {ann.sample_key}",
                        path=ann.sample_key,
                    ),
                )

        existing_labels = await self.label_service.get_by_project(project_id)
        existing_label_names = {self._normalize_label_name(item.name) for item in existing_labels}
        planned_new_labels = sorted(
            {name for name in raw_labels if self._normalize_label_name(name) not in existing_label_names}
        )

        summary = {
            "mode": "project_annotations",
            "project_id": str(project_id),
            "dataset_id": str(dataset_id),
            "branch_name": branch_name,
            "format": fmt.value,
            "total_annotations": len(prepared_annotations),
            "matched_annotations": matched_annotations,
            "skipped_annotations": skipped_annotations,
            "matched_samples": len(matched_sample_ids),
            "unsupported_annotations": sum(unsupported_type_counts.values()),
            "unsupported_types": sorted(unsupported_type_counts.keys()),
        }

        manifest = {
            "mode": "project_annotations",
            "project_id": str(project_id),
            "dataset_id": str(dataset_id),
            "branch_name": branch_name,
            "format": fmt.value,
            "prepared_annotations": [item.to_json() for item in prepared_annotations],
            "planned_new_labels": planned_new_labels,
            "summary": summary,
            "warnings": [item.model_dump(mode="json") for item in warnings],
            "errors": [item.model_dump(mode="json") for item in errors],
        }
        params = {
            "mode": "project_annotations",
            "project_id": str(project_id),
            "dataset_id": str(dataset_id),
            "branch_name": branch_name,
            "format": fmt.value,
        }

        return await self._build_dry_run_response(
            user_id=user_id,
            mode="project_annotations",
            resource_type=ResourceType.PROJECT.value,
            resource_id=project_id,
            zip_asset_id=zip_asset.id,
            manifest=manifest,
            params=params,
            summary=summary,
            warnings=warnings,
            errors=errors,
            planned_new_labels=planned_new_labels,
        )

    async def dry_run_project_associated(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        branch_name: str,
        fmt: ImportFormat,
        target_mode: AssociatedDatasetMode,
        target_dataset_id: uuid.UUID | None,
        new_dataset_name: str | None,
        new_dataset_description: str | None,
        zip_file: UploadFile,
    ) -> ImportDryRunResponse:
        await self._validate_zip_upload(zip_file)
        await self.project_service.get_by_id_or_raise(project_id)
        await self._ensure_branch_exists(project_id=project_id, branch_name=branch_name)

        normalized_target = self._validate_associated_target(
            target_mode=target_mode,
            target_dataset_id=target_dataset_id,
            new_dataset_name=new_dataset_name,
            new_dataset_description=new_dataset_description,
        )

        if normalized_target.mode == AssociatedDatasetMode.EXISTING:
            assert normalized_target.dataset_id is not None
            await self._ensure_project_dataset_context(
                user_id=user_id,
                project_id=project_id,
                dataset_id=normalized_target.dataset_id,
                branch_name=branch_name,
            )

        zip_asset = await self.asset_service.upload_file(
            zip_file,
            meta_info={"temporary": True, "import_mode": "project_associated"},
        )

        warnings: list[ImportIssue] = []
        errors: list[ImportIssue] = []
        image_paths: list[str] = []
        prepared_annotations: list[PreparedAnnotation]
        raw_labels: list[str]

        with tempfile.TemporaryDirectory(prefix="saki-import-associated-") as temp_dir:
            extract_root = Path(temp_dir)
            await zip_file.seek(0)
            with zipfile.ZipFile(zip_file.file) as archive:
                image_paths = self._collect_zip_image_paths(
                    archive,
                    warnings=warnings,
                    errors=errors,
                )
                self._extract_zip_archive(archive, extract_root)

            prepared_annotations, raw_labels, report = self._parse_annotations_from_dir(extract_root, fmt)

        self._append_conversion_report(report, warnings, errors)
        enabled_types = await self._get_project_enabled_annotation_types(project_id)
        enabled_type_values = {item.value for item in enabled_types}
        unsupported_type_counts = self._count_unsupported_annotation_types(
            prepared_annotations=prepared_annotations,
            enabled_type_values=enabled_type_values,
        )
        self._append_unsupported_type_issues(
            errors=errors,
            unsupported_type_counts=unsupported_type_counts,
            enabled_type_values=enabled_type_values,
        )

        if normalized_target.mode == AssociatedDatasetMode.EXISTING:
            assert normalized_target.dataset_id is not None
            existing_rows = await self._list_dataset_sample_rows(normalized_target.dataset_id)
            existing_names = {name for _, name in existing_rows}
            target_names = existing_names | set(image_paths)
        else:
            target_names = set(image_paths)

        name_lookup, basename_lookup = self._build_name_lookup(target_names)

        matched_annotations = 0
        skipped_annotations = 0
        matched_keys: set[str] = set()
        for ann in prepared_annotations:
            resolved_key, via_basename = self._resolve_name(
                ann.sample_key,
                name_lookup,
                basename_lookup,
            )
            if not resolved_key:
                skipped_annotations += 1
                self._append_issue(
                    errors,
                    ImportIssue(
                        code="SAMPLE_NOT_FOUND",
                        message=f"sample key not found in target dataset view: {ann.sample_key}",
                        path=ann.sample_key,
                    ),
                )
                continue
            matched_annotations += 1
            matched_keys.add(resolved_key)
            if via_basename:
                self._append_issue(
                    warnings,
                    ImportIssue(
                        code="SAMPLE_MATCH_BY_BASENAME",
                        message=f"sample matched by basename fallback: {ann.sample_key}",
                        path=ann.sample_key,
                    ),
                )

        existing_label_names: set[str] = set()
        if normalized_target.mode == AssociatedDatasetMode.EXISTING and normalized_target.dataset_id:
            labels = await self.label_service.get_by_project(project_id)
            existing_label_names = {self._normalize_label_name(item.name) for item in labels}

        planned_new_labels = sorted(
            {
                name
                for name in raw_labels
                if self._normalize_label_name(name) not in existing_label_names
            }
        )

        summary = {
            "mode": "project_associated",
            "project_id": str(project_id),
            "branch_name": branch_name,
            "format": fmt.value,
            "target_dataset_mode": normalized_target.mode.value,
            "image_candidates": len(image_paths),
            "total_annotations": len(prepared_annotations),
            "matched_annotations": matched_annotations,
            "skipped_annotations": skipped_annotations,
            "matched_sample_keys": len(matched_keys),
            "unsupported_annotations": sum(unsupported_type_counts.values()),
            "unsupported_types": sorted(unsupported_type_counts.keys()),
        }

        manifest = {
            "mode": "project_associated",
            "project_id": str(project_id),
            "branch_name": branch_name,
            "format": fmt.value,
            "target": normalized_target.model_dump(mode="json"),
            "image_paths": image_paths,
            "prepared_annotations": [item.to_json() for item in prepared_annotations],
            "planned_new_labels": planned_new_labels,
            "summary": summary,
            "warnings": [item.model_dump(mode="json") for item in warnings],
            "errors": [item.model_dump(mode="json") for item in errors],
        }
        params = {
            "mode": "project_associated",
            "project_id": str(project_id),
            "branch_name": branch_name,
            "format": fmt.value,
            "target": normalized_target.model_dump(mode="json"),
        }

        return await self._build_dry_run_response(
            user_id=user_id,
            mode="project_associated",
            resource_type=ResourceType.PROJECT.value,
            resource_id=project_id,
            zip_asset_id=zip_asset.id,
            manifest=manifest,
            params=params,
            summary=summary,
            warnings=warnings,
            errors=errors,
            planned_new_labels=planned_new_labels,
        )

    # ---------------------------------------------------------------------
    # Public execute APIs (task start)
    # ---------------------------------------------------------------------

    async def start_dataset_images_execute(
        self,
        *,
        user_id: uuid.UUID,
        dataset_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> ImportTaskCreateResponse:
        await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="dataset_images",
            user_id=user_id,
            expected_resource_type=ResourceType.DATASET.value,
            expected_resource_id=dataset_id,
            expected_params={
                "mode": "dataset_images",
                "dataset_id": str(dataset_id),
            },
        )

        task = await self.task_service.create_task(
            mode="dataset_images_execute",
            resource_type=ResourceType.DATASET.value,
            resource_id=dataset_id,
            user_id=user_id,
            payload={
                "preview_token": request.preview_token,
            },
        )
        await self.session.commit()

        def producer_factory(session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
            worker = ImportService(session)
            return worker.execute_dataset_images(
                user_id=user_id,
                dataset_id=dataset_id,
                request=ImportExecuteRequest(
                    preview_token=request.preview_token,
                    conflict_strategy=request.conflict_strategy,
                    confirm_create_labels=request.confirm_create_labels,
                ),
            )

        TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
        return self._build_task_create_response(task.id, "queued")

    async def resolve_dataset_image_manifest(
        self,
        *,
        user_id: uuid.UUID,
        dataset_id: uuid.UUID,
        preview_token: str,
    ) -> tuple[uuid.UUID, list[str]]:
        token_payload, manifest = await self._load_and_validate_manifest(
            token=preview_token,
            expected_mode="dataset_images",
            user_id=user_id,
            expected_resource_type=ResourceType.DATASET.value,
            expected_resource_id=dataset_id,
            expected_params={
                "mode": "dataset_images",
                "dataset_id": str(dataset_id),
            },
        )
        image_paths = [str(item) for item in (manifest.get("image_paths") or [])]
        return token_payload.zip_asset_id, image_paths

    async def consume_preview_token(self, token: str) -> None:
        await self._consume_preview_token(token)

    async def start_project_annotations_execute(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> ImportTaskCreateResponse:
        _token_payload, manifest = await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="project_annotations",
            user_id=user_id,
            expected_resource_type=ResourceType.PROJECT.value,
            expected_resource_id=project_id,
        )
        if self._manifest_has_error_code(manifest, "ANNOTATION_TYPE_NOT_ENABLED"):
            raise BadRequestAppException("dry-run contains ANNOTATION_TYPE_NOT_ENABLED; execute is blocked")
        planned_new_labels = list(manifest.get("planned_new_labels") or [])
        if planned_new_labels and not request.confirm_create_labels:
            raise BadRequestAppException("planned_new_labels exists; confirm_create_labels must be true")

        task = await self.task_service.create_task(
            mode="project_annotations_execute",
            resource_type=ResourceType.PROJECT.value,
            resource_id=project_id,
            user_id=user_id,
            payload={
                "preview_token": request.preview_token,
                "conflict_strategy": request.conflict_strategy.value,
                "confirm_create_labels": bool(request.confirm_create_labels),
            },
        )
        await self.session.commit()

        def producer_factory(session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
            worker = ImportService(session)
            return worker.execute_project_annotations(
                user_id=user_id,
                project_id=project_id,
                request=ImportExecuteRequest(
                    preview_token=request.preview_token,
                    conflict_strategy=request.conflict_strategy,
                    confirm_create_labels=request.confirm_create_labels,
                ),
            )

        TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
        return self._build_task_create_response(task.id, "queued")

    async def start_project_associated_execute(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> ImportTaskCreateResponse:
        _token_payload, manifest = await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="project_associated",
            user_id=user_id,
            expected_resource_type=ResourceType.PROJECT.value,
            expected_resource_id=project_id,
        )
        if self._manifest_has_error_code(manifest, "ANNOTATION_TYPE_NOT_ENABLED"):
            raise BadRequestAppException("dry-run contains ANNOTATION_TYPE_NOT_ENABLED; execute is blocked")
        planned_new_labels = list(manifest.get("planned_new_labels") or [])
        if planned_new_labels and not request.confirm_create_labels:
            raise BadRequestAppException("planned_new_labels exists; confirm_create_labels must be true")

        task = await self.task_service.create_task(
            mode="project_associated_execute",
            resource_type=ResourceType.PROJECT.value,
            resource_id=project_id,
            user_id=user_id,
            payload={
                "preview_token": request.preview_token,
                "conflict_strategy": request.conflict_strategy.value,
                "confirm_create_labels": bool(request.confirm_create_labels),
            },
        )
        await self.session.commit()

        def producer_factory(session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
            worker = ImportService(session)
            return worker.execute_project_associated(
                user_id=user_id,
                project_id=project_id,
                request=ImportExecuteRequest(
                    preview_token=request.preview_token,
                    conflict_strategy=request.conflict_strategy,
                    confirm_create_labels=request.confirm_create_labels,
                ),
            )

        TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
        return self._build_task_create_response(task.id, "queued")

    # ---------------------------------------------------------------------
    # Public execute APIs (stream producer, consumed by task worker)
    # ---------------------------------------------------------------------

    async def execute_dataset_images(
        self,
        *,
        user_id: uuid.UUID,
        dataset_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        token_payload, manifest = await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="dataset_images",
            user_id=user_id,
            expected_resource_type=ResourceType.DATASET.value,
            expected_resource_id=dataset_id,
            expected_params={
                "mode": "dataset_images",
                "dataset_id": str(dataset_id),
            },
        )

        image_paths = [str(item) for item in (manifest.get("image_paths") or [])]

        try:
            async for event in self.sample_bulk_service.iter_bulk_import_zip_entries(
                dataset_id=dataset_id,
                zip_asset_id=token_payload.zip_asset_id,
                image_paths=image_paths,
            ):
                yield event
        except Exception as exc:  # noqa: BLE001
            logger.exception("dataset image execute failed dataset_id={} error={}", dataset_id, exc)
            yield self._event_error(
                message=str(exc),
                detail={"code": "EXECUTE_FAILED"},
            )
            yield self._event_complete(
                {
                    "dataset_id": str(dataset_id),
                    "failed": True,
                    "error": str(exc),
                }
            )
        finally:
            await self._consume_preview_token(request.preview_token)

    async def execute_project_annotations(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        token_payload, manifest = await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="project_annotations",
            user_id=user_id,
            expected_resource_type=ResourceType.PROJECT.value,
            expected_resource_id=project_id,
        )

        dataset_id = manifest_dataset_id(manifest)
        branch_name = str(manifest.get("branch_name") or "master")
        fmt = str(manifest.get("format") or "")
        self._assert_preview_params_hash(
            token_payload,
            {
                "mode": "project_annotations",
                "project_id": str(project_id),
                "dataset_id": str(dataset_id),
                "branch_name": branch_name,
                "format": fmt,
            },
        )

        try:
            yield self._event_start(total=len(manifest.get("prepared_annotations") or []), phase="project_annotations_execute")

            commit_id, stats = await self._execute_annotation_manifest(
                user_id=user_id,
                project_id=project_id,
                dataset_id=dataset_id,
                branch_name=branch_name,
                fmt=fmt,
                prepared_annotations=[PreparedAnnotation.from_json(item) for item in (manifest.get("prepared_annotations") or [])],
                planned_new_labels=[str(item) for item in (manifest.get("planned_new_labels") or [])],
                conflict_strategy=request.conflict_strategy,
                confirm_create_labels=request.confirm_create_labels,
            )
            for item in stats.pop("item_events", []):
                yield self._event_annotation(
                    item_key=str(item.get("item_key") or ""),
                    status=str(item.get("status") or "unknown"),
                    message=str(item.get("message") or ""),
                    detail=dict(item.get("detail") or {}),
                )

            payload = {
                "project_id": str(project_id),
                "dataset_id": str(dataset_id),
                "branch_name": branch_name,
                "format": fmt,
                "commit_id": str(commit_id) if commit_id else None,
                **stats,
            }
            yield self._event_complete(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("project annotation execute failed project_id={} error={}", project_id, exc)
            yield self._event_error(
                message=str(exc),
                detail={"code": "EXECUTE_FAILED"},
            )
            yield self._event_complete(
                {
                    "project_id": str(project_id),
                    "dataset_id": str(dataset_id),
                    "branch_name": branch_name,
                    "format": fmt,
                    "failed": True,
                    "error": str(exc),
                }
            )
        finally:
            await self._consume_preview_token(request.preview_token)

    async def execute_project_associated(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        request: ImportExecuteRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        token_payload, manifest = await self._load_and_validate_manifest(
            token=request.preview_token,
            expected_mode="project_associated",
            user_id=user_id,
            expected_resource_type=ResourceType.PROJECT.value,
            expected_resource_id=project_id,
        )

        branch_name = str(manifest.get("branch_name") or "master")
        fmt = str(manifest.get("format") or "")
        image_paths = [str(item) for item in (manifest.get("image_paths") or [])]
        prepared_annotations = [PreparedAnnotation.from_json(item) for item in (manifest.get("prepared_annotations") or [])]
        planned_new_labels = [str(item) for item in (manifest.get("planned_new_labels") or [])]

        target = AssociatedManifestTarget.model_validate(manifest.get("target") or {})
        self._assert_preview_params_hash(
            token_payload,
            {
                "mode": "project_associated",
                "project_id": str(project_id),
                "branch_name": branch_name,
                "format": fmt,
                "target": target.model_dump(mode="json"),
            },
        )

        try:
            total = len(image_paths) + len(prepared_annotations)
            yield self._event_start(total=total, phase="project_associated_execute")

            dataset = await self._resolve_associated_target_dataset(
                user_id=user_id,
                project_id=project_id,
                target=target,
            )

            image_stats = {
                "imported_samples": 0,
                "reused_samples": 0,
                "failed_samples": 0,
            }

            yield self._event_phase(phase="dataset_images_execute", message="importing image package", current=0, total=len(image_paths))

            if image_paths:
                async for event in self.sample_bulk_service.iter_bulk_import_zip_entries(
                    dataset_id=dataset.id,
                    zip_asset_id=token_payload.zip_asset_id,
                    image_paths=image_paths,
                ):
                    event_name = str(event.get("event") or "")
                    if event_name == "complete":
                        detail = dict(event.get("detail") or {})
                        image_stats["imported_samples"] = int(detail.get("imported_samples") or 0)
                        image_stats["reused_samples"] = int(detail.get("reused_samples") or 0)
                        image_stats["failed_samples"] = int(detail.get("failed_samples") or 0)
                        yield self._event_phase(
                            phase="dataset_images_execute",
                            message="image package import completed",
                            current=len(image_paths),
                            total=len(image_paths),
                        )
                        continue
                    yield event

            yield self._event_phase(phase="project_annotations_execute", message="importing annotations", current=0, total=len(prepared_annotations))

            commit_id, ann_stats = await self._execute_annotation_manifest(
                user_id=user_id,
                project_id=project_id,
                dataset_id=dataset.id,
                branch_name=branch_name,
                fmt=fmt,
                prepared_annotations=prepared_annotations,
                planned_new_labels=planned_new_labels,
                conflict_strategy=request.conflict_strategy,
                confirm_create_labels=request.confirm_create_labels,
            )
            for item in ann_stats.pop("item_events", []):
                yield self._event_annotation(
                    item_key=str(item.get("item_key") or ""),
                    status=str(item.get("status") or "unknown"),
                    message=str(item.get("message") or ""),
                    detail=dict(item.get("detail") or {}),
                )

            yield self._event_complete(
                {
                    "project_id": str(project_id),
                    "dataset_id": str(dataset.id),
                    "branch_name": branch_name,
                    "format": fmt,
                    "target_dataset_mode": target.mode.value,
                    "commit_id": str(commit_id) if commit_id else None,
                    **image_stats,
                    **ann_stats,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("project associated execute failed project_id={} error={}", project_id, exc)
            yield self._event_error(
                message=str(exc),
                detail={"code": "EXECUTE_FAILED"},
            )
            yield self._event_complete(
                {
                    "project_id": str(project_id),
                    "branch_name": branch_name,
                    "format": fmt,
                    "target_dataset_mode": target.mode.value,
                    "failed": True,
                    "error": str(exc),
                }
            )
        finally:
            await self._consume_preview_token(request.preview_token)

    # ---------------------------------------------------------------------
    # Core execution helpers
    # ---------------------------------------------------------------------

    async def _execute_annotation_manifest(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        branch_name: str,
        fmt: str,
        prepared_annotations: list[PreparedAnnotation],
        planned_new_labels: list[str],
        conflict_strategy: ConflictStrategy,
        confirm_create_labels: bool,
    ) -> tuple[uuid.UUID | None, dict[str, Any]]:
        await self._ensure_project_dataset_context(
            user_id=user_id,
            project_id=project_id,
            dataset_id=dataset_id,
            branch_name=branch_name,
        )
        project_enabled_types = await self._get_project_enabled_annotation_types(project_id)
        enabled_type_values = {item.value for item in project_enabled_types}

        if planned_new_labels and not confirm_create_labels:
            raise BadRequestAppException("planned_new_labels exists; confirm_create_labels must be true")

        label_rows = await self.label_service.get_by_project(project_id)
        labels_by_name = {self._normalize_label_name(item.name): item for item in label_rows}

        created_label_count = 0
        if planned_new_labels:
            for label_name in planned_new_labels:
                normalized = self._normalize_label_name(label_name)
                if normalized in labels_by_name:
                    continue
                created = await self.label_service.create_label(
                    LabelCreate(
                        project_id=project_id,
                        name=label_name,
                        color=self._color_for_label(label_name),
                    )
                )
                labels_by_name[normalized] = created
                created_label_count += 1

        sample_rows = await self._list_dataset_sample_rows(dataset_id)
        sample_lookup, basename_lookup = self._build_sample_lookup(sample_rows)

        imported_by_sample: dict[uuid.UUID, list[dict[str, Any]]] = {}
        skipped_annotations = 0
        matched_annotations = 0
        touched_sample_ids: set[uuid.UUID] = set()
        item_events: list[dict[str, Any]] = []
        omitted_item_events = 0

        def append_item_event(payload: dict[str, Any]) -> None:
            nonlocal omitted_item_events
            if len(item_events) >= _MAX_EXECUTION_ITEM_EVENTS:
                omitted_item_events += 1
                return
            item_events.append(payload)

        for ann in prepared_annotations:
            if ann.ann_type not in enabled_type_values:
                skipped_annotations += 1
                append_item_event(
                    {
                        "item_key": ann.sample_key,
                        "status": "skipped",
                        "message": f"{ann.sample_key}: annotation type {ann.ann_type} is not enabled",
                        "detail": {
                            "code": "ANNOTATION_TYPE_NOT_ENABLED",
                            "type": ann.ann_type,
                            "enabled_types": sorted(enabled_type_values),
                        },
                    }
                )
                continue

            sample_id, _via_basename = self._resolve_sample_id(
                ann.sample_key,
                sample_lookup,
                basename_lookup,
            )
            if sample_id is None:
                skipped_annotations += 1
                append_item_event(
                    {
                        "item_key": ann.sample_key,
                        "status": "skipped",
                        "message": f"{ann.sample_key}: sample not found in target dataset",
                        "detail": {"code": "SAMPLE_NOT_FOUND"},
                    }
                )
                continue

            normalized_label_name = self._normalize_label_name(ann.label_name)
            target_label = labels_by_name.get(normalized_label_name)
            if target_label is None:
                skipped_annotations += 1
                append_item_event(
                    {
                        "item_key": ann.sample_key,
                        "status": "skipped",
                        "message": f"{ann.sample_key}: label not found ({ann.label_name})",
                        "detail": {"code": "LABEL_NOT_FOUND", "label": ann.label_name},
                    }
                )
                continue

            lineage_id = self._deterministic_uuid(
                "lineage",
                str(project_id),
                str(dataset_id),
                ann.sample_key,
                ann.lineage_seed,
            )
            group_id = self._deterministic_uuid(
                "group",
                str(project_id),
                str(dataset_id),
                ann.sample_key,
                ann.lineage_seed,
            )

            payload = {
                "sample_id": str(sample_id),
                "label_id": str(target_label.id),
                "group_id": str(group_id),
                "lineage_id": str(lineage_id),
                "view_role": "main",
                "type": ann.ann_type,
                "source": "imported",
                "geometry": ann.geometry,
                "attrs": ann.attrs,
                "confidence": ann.confidence,
                "annotator_id": str(user_id),
            }
            imported_by_sample.setdefault(sample_id, []).append(payload)
            touched_sample_ids.add(sample_id)
            matched_annotations += 1

        if not touched_sample_ids:
            return None, {
                "matched_annotations": 0,
                "skipped_annotations": skipped_annotations,
                "created_labels": created_label_count,
                "strategy": conflict_strategy.value,
                "omitted_item_events": omitted_item_events,
                "item_events": item_events,
            }

        branch_repo = BranchRepository(self.session)
        branch = await branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            raise NotFoundAppException(f"Branch '{branch_name}' not found in project")

        final_by_sample: dict[uuid.UUID, list[dict[str, Any]]]
        if conflict_strategy == ConflictStrategy.REPLACE:
            final_by_sample = imported_by_sample
        else:
            final_by_sample = {}
            head_commit_id = branch.head_commit_id
            existing_by_sample: dict[uuid.UUID, list[Annotation]] = {}
            if head_commit_id:
                existing_by_sample = await self.annotation_gateway.get_annotations_by_commit_and_samples(
                    commit_id=head_commit_id,
                    sample_ids=list(touched_sample_ids),
                )
            for sample_id in touched_sample_ids:
                merged: dict[str, dict[str, Any]] = {}
                for existing in existing_by_sample.get(sample_id, []):
                    merged[str(existing.lineage_id)] = self._annotation_to_change_payload(existing, user_id)
                for imported in imported_by_sample.get(sample_id, []):
                    merged[str(imported["lineage_id"])] = imported
                final_by_sample[sample_id] = list(merged.values())

        flattened_changes: list[dict[str, Any]] = []
        for sample_id in touched_sample_ids:
            flattened_changes.extend(final_by_sample.get(sample_id, []))

        commit = await self.annotation_bulk_service.save_annotations(
            project_id=project_id,
            branch_name=branch_name,
            annotation_changes=flattened_changes,
            commit_message=f"Import annotations ({fmt}, {conflict_strategy.value})",
            author_id=user_id,
            touched_sample_ids=list(touched_sample_ids),
        )

        return commit.id, {
            "matched_annotations": matched_annotations,
            "skipped_annotations": skipped_annotations,
            "created_labels": created_label_count,
            "touched_samples": len(touched_sample_ids),
            "strategy": conflict_strategy.value,
            "omitted_item_events": omitted_item_events,
            "item_events": item_events,
        }

    async def _resolve_associated_target_dataset(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        target: AssociatedManifestTarget,
    ):
        if target.mode == AssociatedDatasetMode.EXISTING:
            if target.dataset_id is None:
                raise BadRequestAppException("target_dataset_id is required for existing target mode")

            checker = PermissionChecker(self.session)
            allowed = await checker.check(
                user_id=user_id,
                permission=Permissions.DATASET_IMPORT,
                resource_type=ResourceType.DATASET,
                resource_id=str(target.dataset_id),
            )
            if not allowed:
                raise ForbiddenAppException(
                    f"Permission denied: {Permissions.DATASET_IMPORT} on dataset {target.dataset_id}"
                )

            dataset = await self.dataset_service.get_by_id_or_raise(target.dataset_id)
            self._ensure_dataset_type_classic(dataset.type)

            linked_dataset_ids = set(await self.project_service.repository.get_linked_dataset_ids(project_id))
            if target.dataset_id not in linked_dataset_ids:
                raise BadRequestAppException(
                    f"Dataset {target.dataset_id} is not linked to project {project_id}"
                )
            return dataset

        dataset_name = str(target.new_dataset_name or "").strip()
        if not dataset_name:
            raise BadRequestAppException("new_dataset_name is required for new target mode")

        checker = PermissionChecker(self.session)
        can_create_dataset = await checker.check(
            user_id=user_id,
            permission=Permissions.DATASET_CREATE_ALL,
        )
        if not can_create_dataset:
            raise ForbiddenAppException(
                f"Permission denied: {Permissions.DATASET_CREATE_ALL}"
            )

        created = await self.dataset_service.create_dataset(
            DatasetCreate(
                name=dataset_name,
                description=target.new_dataset_description,
                type=DatasetType.CLASSIC,
            ),
            owner_id=user_id,
        )

        await self.project_service.link_datasets(
            project_id=project_id,
            dataset_ids=[created.id],
            actor_user_id=user_id,
        )
        return created

    # ---------------------------------------------------------------------
    # Manifest / token helpers
    # ---------------------------------------------------------------------

    async def _build_dry_run_response(
        self,
        *,
        user_id: uuid.UUID,
        mode: str,
        resource_type: str,
        resource_id: uuid.UUID,
        zip_asset_id: uuid.UUID,
        manifest: dict[str, Any],
        params: dict[str, Any],
        summary: dict[str, Any],
        warnings: list[ImportIssue],
        errors: list[ImportIssue],
        planned_new_labels: list[str],
    ) -> ImportDryRunResponse:
        manifest_asset = await self._store_manifest_asset(mode=mode, manifest=manifest)
        preview_payload = await self._create_preview_token(
            mode=mode,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            zip_asset_id=zip_asset_id,
            manifest_asset_id=manifest_asset.id,
            params_hash=self._hash_payload(params),
        )

        return ImportDryRunResponse(
            preview_token=preview_payload.token,
            expires_at=preview_payload.expires_at,
            summary=summary,
            planned_new_labels=planned_new_labels,
            warnings=warnings,
            errors=errors,
        )

    async def _create_preview_token(
        self,
        *,
        mode: str,
        user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        zip_asset_id: uuid.UUID,
        manifest_asset_id: uuid.UUID,
        params_hash: str,
    ) -> PreviewTokenPayload:
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(minutes=settings.IMPORT_PREVIEW_TTL_MINUTES)
        token = uuid.uuid4().hex

        payload = PreviewTokenPayload(
            token=token,
            mode=mode,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            zip_asset_id=zip_asset_id,
            manifest_asset_id=manifest_asset_id,
            params_hash=params_hash,
            created_at=created_at,
            expires_at=expires_at,
        )

        redis = get_redis_client()
        await redis.set(
            self._preview_token_key(token),
            json.dumps(payload.to_json()),
            ex=max(1, int(settings.IMPORT_PREVIEW_TTL_MINUTES * 60)),
        )

        return payload

    async def _store_manifest_asset(self, *, mode: str, manifest: dict[str, Any]):
        encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        upload = UploadFile(
            file=BytesIO(encoded),
            filename=f"{mode}-manifest.json",
            headers=Headers({"content-type": "application/json"}),
        )
        return await self.asset_service.upload_file(
            upload,
            meta_info={"temporary": True, "import_manifest": True, "mode": mode},
        )

    async def _load_and_validate_manifest(
        self,
        *,
        token: str,
        expected_mode: str,
        user_id: uuid.UUID,
        expected_resource_type: str,
        expected_resource_id: uuid.UUID,
        expected_params: dict[str, Any] | None = None,
    ) -> tuple[PreviewTokenPayload, dict[str, Any]]:
        preview = await self._get_preview_token_payload(token)

        if preview.mode != expected_mode:
            raise BadRequestAppException("preview_token mode mismatch")
        if preview.user_id != user_id:
            raise ForbiddenAppException("preview_token does not belong to current user")
        if preview.resource_type != expected_resource_type or preview.resource_id != expected_resource_id:
            raise BadRequestAppException("preview_token resource mismatch")

        if expected_params is not None:
            self._assert_preview_params_hash(preview, expected_params)

        manifest_bytes = await self.asset_service.get_object_bytes(preview.manifest_asset_id)
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise BadRequestAppException(f"failed to decode preview manifest: {exc}") from exc

        return preview, manifest

    @staticmethod
    def _assert_preview_params_hash(preview: PreviewTokenPayload, params: dict[str, Any]) -> None:
        expected_hash = ImportService._hash_payload(params)
        if preview.params_hash != expected_hash:
            raise BadRequestAppException("preview_token parameter hash mismatch")

    async def _get_preview_token_payload(self, token: str) -> PreviewTokenPayload:
        redis = get_redis_client()
        raw = await redis.get(self._preview_token_key(token))
        if not raw:
            raise BadRequestAppException("Invalid or expired preview_token")

        try:
            payload = json.loads(raw)
            parsed = PreviewTokenPayload.from_json(payload)
        except Exception as exc:  # noqa: BLE001
            raise BadRequestAppException(f"Invalid preview_token payload: {exc}") from exc

        now = datetime.now(UTC)
        if parsed.expires_at <= now:
            await redis.delete(self._preview_token_key(token))
            raise BadRequestAppException("preview_token expired")
        return parsed

    async def _consume_preview_token(self, token: str) -> None:
        redis = get_redis_client()
        await redis.delete(self._preview_token_key(token))

    @staticmethod
    def _preview_token_key(token: str) -> str:
        return f"{_PREVIEW_TOKEN_KEY}:{token}"

    # ---------------------------------------------------------------------
    # Zip helpers
    # ---------------------------------------------------------------------

    async def _validate_zip_upload(self, file: UploadFile) -> None:
        filename = str(file.filename or "").lower()
        if not filename.endswith(".zip"):
            raise BadRequestAppException("Only ZIP archives are supported")

        size = self._upload_file_size(file)
        if size > settings.IMPORT_MAX_ZIP_BYTES:
            raise BadRequestAppException(
                f"ZIP size exceeds limit ({size} > {settings.IMPORT_MAX_ZIP_BYTES})"
            )

        await file.seek(0)
        magic = await file.read(4)
        await file.seek(0)
        if magic not in _ZIP_MAGIC:
            raise BadRequestAppException("Invalid ZIP file")

    @staticmethod
    def _upload_file_size(file: UploadFile) -> int:
        file.file.seek(0, 2)
        size = int(file.file.tell())
        file.file.seek(0)
        return size

    def _collect_zip_image_paths(
        self,
        archive: zipfile.ZipFile,
        *,
        warnings: list[ImportIssue],
        errors: list[ImportIssue],
    ) -> list[str]:
        image_paths: list[str] = []
        del errors
        total_uncompressed = 0
        total_files = 0

        allowed_exts = {ext.lower() for ext in settings.IMPORT_ALLOWED_IMAGE_EXTS}
        infos = archive.infolist()
        if len(infos) > settings.IMPORT_MAX_ENTRIES:
            raise BadRequestAppException(
                f"ZIP entry count exceeds limit ({len(infos)} > {settings.IMPORT_MAX_ENTRIES})"
            )

        for info in infos:
            if info.is_dir():
                continue

            normalized = self._normalize_zip_entry_name(info.filename)
            if not normalized:
                continue

            if self._zip_entry_is_symlink(info):
                self._append_issue(
                    warnings,
                    ImportIssue(
                        code="ZIP_SYMLINK_SKIPPED",
                        message=f"symlink entry skipped: {normalized}",
                        path=normalized,
                    ),
                )
                continue

            total_files += 1
            total_uncompressed += max(0, int(info.file_size or 0))
            if total_uncompressed > settings.IMPORT_MAX_ZIP_BYTES * 8:
                raise BadRequestAppException("ZIP appears to be a decompression bomb")

            ext = Path(normalized).suffix.lower()
            if ext in allowed_exts:
                image_paths.append(normalized)

        self._last_scan_total_files = total_files
        return image_paths

    def _extract_zip_archive(self, archive: zipfile.ZipFile, output_dir: Path) -> None:
        infos = archive.infolist()
        if len(infos) > settings.IMPORT_MAX_ENTRIES:
            raise BadRequestAppException(
                f"ZIP entry count exceeds limit ({len(infos)} > {settings.IMPORT_MAX_ENTRIES})"
            )

        total_uncompressed = 0
        for info in infos:
            if info.is_dir():
                continue

            normalized = self._normalize_zip_entry_name(info.filename)
            if not normalized:
                continue
            if self._zip_entry_is_symlink(info):
                continue

            total_uncompressed += max(0, int(info.file_size or 0))
            if total_uncompressed > settings.IMPORT_MAX_ZIP_BYTES * 8:
                raise BadRequestAppException("ZIP appears to be a decompression bomb")

            target = (output_dir / normalized).resolve()
            if not str(target).startswith(str(output_dir.resolve())):
                raise BadRequestAppException(f"ZIP path traversal detected: {normalized}")

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    @staticmethod
    def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
        mode = (info.external_attr >> 16) & 0o170000
        return mode == 0o120000

    @staticmethod
    def _normalize_zip_entry_name(raw_name: str) -> str:
        name = str(raw_name or "").replace("\\", "/").strip()
        while name.startswith("./"):
            name = name[2:]
        if not name or name.endswith("/"):
            return ""
        if name.startswith("/"):
            raise BadRequestAppException(f"invalid zip entry path: {raw_name}")

        parts = [part for part in name.split("/") if part and part != "."]
        if not parts:
            return ""
        if any(part == ".." for part in parts):
            raise BadRequestAppException(f"invalid zip entry path: {raw_name}")
        if ":" in parts[0]:
            raise BadRequestAppException(f"invalid zip entry path: {raw_name}")
        return "/".join(parts)

    @staticmethod
    def _build_upload_from_zip_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> UploadFile:
        normalized = ImportService._normalize_zip_entry_name(info.filename)
        if not normalized:
            raise BadRequestAppException("invalid zip entry")
        mime_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"

        temp_file = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        with archive.open(info) as src:
            shutil.copyfileobj(src, temp_file)
        temp_file.seek(0)

        return UploadFile(
            file=temp_file,
            filename=normalized,
            headers=Headers({"content-type": mime_type}),
        )

    # ---------------------------------------------------------------------
    # Annotation parse helpers
    # ---------------------------------------------------------------------

    def _parse_annotations_from_dir(
        self,
        root: Path,
        fmt: ImportFormat,
    ) -> tuple[list[PreparedAnnotation], list[str], ConversionReport]:
        ctx = ConversionContext(
            strict=False,
            include_external_ref=True,
            emit_labels=True,
            read_images=True,
            yolo_is_normalized=True,
        )
        report = ConversionReport()

        if fmt == ImportFormat.COCO:
            coco_json = self._find_coco_json(root)
            if coco_json is None:
                raise BadRequestAppException("COCO annotation json not found in ZIP")
            batch = load_coco_dataset(coco_json, image_root=root, ctx=ctx, report=report)
        elif fmt == ImportFormat.VOC:
            voc_root = self._find_voc_root(root)
            if voc_root is None:
                raise BadRequestAppException("VOC dataset structure not found in ZIP")
            split = self._build_voc_import_split(voc_root)
            batch = load_voc_dataset(voc_root, split=split, ctx=ctx, report=report)
        elif fmt == ImportFormat.YOLO:
            yolo_root = self._find_yolo_root(root)
            if yolo_root is None:
                raise BadRequestAppException("YOLO dataset structure not found in ZIP")
            split = self._pick_yolo_split(yolo_root)
            yolo_format = self._detect_yolo_label_format(yolo_root, split)
            batch = load_yolo_dataset(
                yolo_root,
                split=split,
                ctx=ConversionContext(
                    strict=False,
                    include_external_ref=True,
                    emit_labels=True,
                    read_images=True,
                    yolo_is_normalized=True,
                    yolo_label_format=yolo_format,
                ),
                report=report,
            )
        else:
            raise BadRequestAppException(f"Unsupported annotation format: {fmt.value}")

        labels_by_id, samples, annotations = split_batch(batch, ctx=ctx, report=report)

        sample_by_id = {sample.id: sample for sample in samples}
        raw_labels: list[str] = []
        prepared: list[PreparedAnnotation] = []

        for label in labels_by_id.values():
            if label.name:
                raw_labels.append(str(label.name))

        for index, ann in enumerate(annotations):
            sample = sample_by_id.get(ann.sample_id)
            if sample is None:
                report.error(f"annotation.sample_id missing in sample table: {ann.sample_id}")
                continue

            sample_key = self._extract_sample_key(sample)
            if not sample_key:
                report.error(f"sample key unavailable for sample_id={sample.id}")
                continue

            shape = ann.geometry.WhichOneof("shape") if ann.HasField("geometry") else None
            if shape not in {"rect", "obb"}:
                report.error(f"unsupported geometry type: {shape}")
                continue

            if shape == "rect":
                rect = ann.geometry.rect
                geometry = {
                    "rect": {
                        "x": float(rect.x),
                        "y": float(rect.y),
                        "width": float(rect.width),
                        "height": float(rect.height),
                    }
                }
                ann_type = "rect"
            else:
                obb = ann.geometry.obb
                geometry = {
                    "obb": {
                        "cx": float(obb.cx),
                        "cy": float(obb.cy),
                        "width": float(obb.width),
                        "height": float(obb.height),
                        "angle_deg_ccw": float(obb.angle_deg_ccw),
                    }
                }
                ann_type = "obb"

            label_name = labels_by_id.get(ann.label_id).name if ann.label_id in labels_by_id else ann.label_id
            if not label_name:
                label_name = f"label_{ann.label_id}"

            attrs = struct_to_dict(ann.attrs) if ann.HasField("attrs") else {}
            external = attrs.get("external", {}) if isinstance(attrs, dict) else {}
            lineage_seed = str(
                external.get("ann_key")
                or ann.id
                or f"{sample_key}:{index}"
            )

            prepared.append(
                PreparedAnnotation(
                    sample_key=sample_key,
                    label_name=str(label_name),
                    ann_type=ann_type,
                    geometry=geometry,
                    confidence=float(ann.confidence or 1.0),
                    attrs=attrs if isinstance(attrs, dict) else {},
                    lineage_seed=lineage_seed,
                )
            )

        return prepared, raw_labels, report

    @staticmethod
    def _extract_sample_key(sample) -> str:
        key = ""
        if sample.HasField("meta"):
            meta = struct_to_dict(sample.meta)
            external = meta.get("external", {}) if isinstance(meta, dict) else {}
            key = str(
                external.get("relpath")
                or external.get("file_name")
                or external.get("sample_key")
                or ""
            )
        if not key:
            key = str(sample.id)
        return ImportService._normalize_name_key(key)

    @staticmethod
    def _find_coco_json(root: Path) -> Path | None:
        candidates = sorted(root.rglob("*.json"))
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict) and {"images", "annotations", "categories"}.issubset(payload.keys()):
                return path
        return None

    @staticmethod
    def _find_voc_root(root: Path) -> Path | None:
        candidates = [root] + [item for item in root.iterdir() if item.is_dir()]
        for candidate in candidates:
            if (candidate / "Annotations").is_dir() and (candidate / "ImageSets" / "Main").is_dir():
                return candidate
        return None

    @staticmethod
    def _build_voc_import_split(voc_root: Path) -> str:
        main_dir = voc_root / "ImageSets" / "Main"
        keys: set[str] = set()

        def collect_keys(split_file: Path) -> None:
            try:
                lines = split_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                return
            for line in lines:
                text = line.strip()
                if not text:
                    continue
                key = text.split()[0].strip()
                if key:
                    keys.add(key)

        # Prefer canonical detection/segmentation split files first.
        for name in ("train", "trainval", "val", "test"):
            split_path = main_dir / f"{name}.txt"
            if split_path.exists():
                collect_keys(split_path)

        # Fallback to any txt under ImageSets/Main.
        if not keys:
            for split_path in sorted(main_dir.glob("*.txt")):
                collect_keys(split_path)

        # Import scenario should not silently drop XMLs that are absent in split files.
        ann_dir = voc_root / "Annotations"
        if ann_dir.is_dir():
            for xml_path in sorted(ann_dir.glob("*.xml")):
                if xml_path.stem:
                    keys.add(xml_path.stem)

        if not keys:
            raise BadRequestAppException("VOC split file not found under ImageSets/Main")

        split_name = "__saki_import_all__"
        split_path = main_dir / f"{split_name}.txt"
        split_path.write_text(
            "\n".join(sorted(keys)) + "\n",
            encoding="utf-8",
        )
        return split_name

    @staticmethod
    def _find_yolo_root(root: Path) -> Path | None:
        candidates = [root] + [item for item in root.iterdir() if item.is_dir()]
        for candidate in candidates:
            if (candidate / "images").is_dir() and (candidate / "labels").is_dir():
                return candidate
        return None

    @staticmethod
    def _pick_yolo_split(yolo_root: Path) -> str:
        image_splits = {item.name for item in (yolo_root / "images").iterdir() if item.is_dir()}
        label_splits = {item.name for item in (yolo_root / "labels").iterdir() if item.is_dir()}

        for split in ("train", "val", "test"):
            if split in image_splits and split in label_splits:
                return split

        shared = sorted(image_splits & label_splits)
        if shared:
            return shared[0]

        raise BadRequestAppException("YOLO split folders not found (expected images/<split> and labels/<split>)")

    @staticmethod
    def _detect_yolo_label_format(yolo_root: Path, split: str) -> str:
        label_dir = yolo_root / "labels" / split
        txt_files = sorted(label_dir.rglob("*.txt"))
        for txt_path in txt_files:
            try:
                lines = txt_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                raw = line.strip()
                if not raw:
                    continue
                count = len(raw.split()) - 1
                if count == 8:
                    return "obb_poly8"
                if count == 5:
                    return "obb_rbox"
                if count == 4:
                    return "det"
        return "det"

    # ---------------------------------------------------------------------
    # Data lookup helpers
    # ---------------------------------------------------------------------

    async def _list_dataset_sample_rows(self, dataset_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        stmt = select(Sample.id, Sample.name).where(Sample.dataset_id == dataset_id)
        result = await self.session.exec(stmt)
        rows = [(sample_id, self._normalize_name_key(name)) for sample_id, name in result.all()]
        return [item for item in rows if item[1]]

    async def _list_dataset_sample_names(self, dataset_id: uuid.UUID) -> list[str]:
        rows = await self._list_dataset_sample_rows(dataset_id)
        return [name for _sample_id, name in rows]

    @staticmethod
    def _build_sample_lookup(
        rows: list[tuple[uuid.UUID, str]],
    ) -> tuple[dict[str, uuid.UUID], dict[str, uuid.UUID]]:
        exact: dict[str, uuid.UUID] = {}
        basename_bucket: dict[str, set[uuid.UUID]] = {}

        for sample_id, name in rows:
            exact[name] = sample_id
            base = Path(name).name
            basename_bucket.setdefault(base, set()).add(sample_id)

        basename_unique: dict[str, uuid.UUID] = {}
        for base, values in basename_bucket.items():
            if len(values) == 1:
                basename_unique[base] = next(iter(values))

        return exact, basename_unique

    @staticmethod
    def _build_name_lookup(names: set[str]) -> tuple[set[str], dict[str, str]]:
        exact = {ImportService._normalize_name_key(item) for item in names if item}
        bucket: dict[str, set[str]] = {}
        for name in exact:
            bucket.setdefault(Path(name).name, set()).add(name)

        basename_unique: dict[str, str] = {}
        for base, values in bucket.items():
            if len(values) == 1:
                basename_unique[base] = next(iter(values))

        return exact, basename_unique

    @staticmethod
    def _resolve_sample_id(
        sample_key: str,
        exact: dict[str, uuid.UUID],
        basename_unique: dict[str, uuid.UUID],
    ) -> tuple[uuid.UUID | None, bool]:
        key = ImportService._normalize_name_key(sample_key)
        if not key:
            return None, False

        if key in exact:
            return exact[key], False

        base = Path(key).name
        if base in basename_unique:
            return basename_unique[base], True

        return None, False

    @staticmethod
    def _resolve_name(
        sample_key: str,
        exact: set[str],
        basename_unique: dict[str, str],
    ) -> tuple[str | None, bool]:
        key = ImportService._normalize_name_key(sample_key)
        if not key:
            return None, False

        if key in exact:
            return key, False

        base = Path(key).name
        if base in basename_unique:
            return basename_unique[base], True

        return None, False

    @staticmethod
    def _normalize_name_key(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    # ---------------------------------------------------------------------
    # Context validation helpers
    # ---------------------------------------------------------------------

    async def _ensure_project_dataset_context(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        branch_name: str,
    ) -> None:
        project = await self.project_service.get_by_id_or_raise(project_id)
        del project

        dataset = await self.dataset_service.get_by_id_or_raise(dataset_id)
        self._ensure_dataset_type_classic(dataset.type)

        linked_dataset_ids = set(await self.project_service.repository.get_linked_dataset_ids(project_id))
        if dataset_id not in linked_dataset_ids:
            raise BadRequestAppException(f"Dataset {dataset_id} is not linked to project {project_id}")

        await self._ensure_branch_exists(project_id=project_id, branch_name=branch_name)

    async def _ensure_branch_exists(self, *, project_id: uuid.UUID, branch_name: str) -> None:
        branch_repo = BranchRepository(self.session)
        branch = await branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            raise NotFoundAppException(f"Branch '{branch_name}' not found in project")

    @staticmethod
    def _ensure_dataset_type_classic(dataset_type: DatasetType) -> None:
        if dataset_type != DatasetType.CLASSIC:
            raise BadRequestAppException("Import only supports classic datasets in this release")

    @staticmethod
    def _validate_associated_target(
        *,
        target_mode: AssociatedDatasetMode,
        target_dataset_id: uuid.UUID | None,
        new_dataset_name: str | None,
        new_dataset_description: str | None,
    ) -> AssociatedManifestTarget:
        if target_mode == AssociatedDatasetMode.EXISTING:
            if target_dataset_id is None:
                raise BadRequestAppException("target_dataset_id is required when target_dataset_mode=existing")
            return AssociatedManifestTarget(mode=target_mode, dataset_id=target_dataset_id)

        name = str(new_dataset_name or "").strip()
        if not name:
            raise BadRequestAppException("new_dataset_name is required when target_dataset_mode=new")
        return AssociatedManifestTarget(
            mode=target_mode,
            new_dataset_name=name,
            new_dataset_description=new_dataset_description,
        )

    async def _get_project_enabled_annotation_types(self, project_id: uuid.UUID) -> list[AnnotationType]:
        project = await self.project_service.get_by_id_or_raise(project_id)
        return normalize_enabled_annotation_types(project.enabled_annotation_types or [])

    @staticmethod
    def _count_unsupported_annotation_types(
        *,
        prepared_annotations: list[PreparedAnnotation],
        enabled_type_values: set[str],
    ) -> dict[str, int]:
        unsupported: dict[str, int] = {}
        for ann in prepared_annotations:
            ann_type = str(ann.ann_type or "").strip().lower()
            if not ann_type:
                continue
            if ann_type in enabled_type_values:
                continue
            unsupported[ann_type] = unsupported.get(ann_type, 0) + 1
        return unsupported

    @staticmethod
    def _append_unsupported_type_issues(
        *,
        errors: list[ImportIssue],
        unsupported_type_counts: dict[str, int],
        enabled_type_values: set[str],
    ) -> None:
        for ann_type, count in sorted(unsupported_type_counts.items()):
            ImportService._append_issue(
                errors,
                ImportIssue(
                    code="ANNOTATION_TYPE_NOT_ENABLED",
                    message=f"annotation type {ann_type} is not enabled for this project",
                    detail={
                        "annotation_type": ann_type,
                        "count": count,
                        "enabled_types": sorted(enabled_type_values),
                    },
                ),
            )

    # ---------------------------------------------------------------------
    # Serialization helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _append_issue(target: list[ImportIssue], issue: ImportIssue) -> None:
        if len(target) >= _MAX_ISSUES_PER_KIND:
            return
        target.append(issue)

    @staticmethod
    def _append_conversion_report(
        report: ConversionReport,
        warnings: list[ImportIssue],
        errors: list[ImportIssue],
    ) -> None:
        for item in report.warnings:
            ImportService._append_issue(
                warnings,
                ImportIssue(code="CONVERT_WARNING", message=str(item)),
            )
        for item in report.errors:
            ImportService._append_issue(
                errors,
                ImportIssue(code="CONVERT_ERROR", message=str(item)),
            )

    @staticmethod
    def _manifest_has_error_code(manifest: dict[str, Any], code: str) -> bool:
        target = str(code or "").strip().upper()
        if not target:
            return False
        for item in manifest.get("errors") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("code") or "").strip().upper() == target:
                return True
        return False

    @staticmethod
    def _build_task_create_response(task_id: uuid.UUID, status: str) -> ImportTaskCreateResponse:
        base = f"{settings.API_V1_STR}/imports/tasks/{task_id}"
        return ImportTaskCreateResponse(
            task_id=task_id,
            status=status,
            stream_url=f"{base}/events?after_seq=0",
            status_url=base,
        )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_label_name(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _color_for_label(label_name: str) -> str:
        digest = hashlib.sha1(label_name.encode("utf-8")).hexdigest()
        return f"#{digest[:6]}"

    @staticmethod
    def _deterministic_uuid(*parts: str) -> uuid.UUID:
        key = "::".join(parts)
        return uuid.uuid5(_IMPORT_UUID_NAMESPACE, key)

    @staticmethod
    def _annotation_to_change_payload(annotation: Annotation, default_annotator: uuid.UUID) -> dict[str, Any]:
        return {
            "sample_id": str(annotation.sample_id),
            "label_id": str(annotation.label_id),
            "group_id": str(annotation.group_id),
            "lineage_id": str(annotation.lineage_id),
            "view_role": annotation.view_role,
            "type": annotation.type.value if hasattr(annotation.type, "value") else str(annotation.type),
            "source": annotation.source.value if hasattr(annotation.source, "value") else str(annotation.source),
            "geometry": dict(annotation.geometry or {}),
            "attrs": dict(annotation.attrs or {}),
            "confidence": float(annotation.confidence),
            "annotator_id": str(annotation.annotator_id or default_annotator),
        }

    # ---------------------------------------------------------------------
    # SSE helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _event_start(*, total: int, phase: str) -> dict[str, Any]:
        return {
            "event": "start",
            "phase": phase,
            "total": total,
            "current": 0,
            "message": "import task started",
        }

    @staticmethod
    def _event_phase(
        *,
        phase: str,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "phase",
            "phase": phase,
            "message": message,
        }
        if current is not None:
            payload["current"] = current
        if total is not None:
            payload["total"] = total
        return payload

    @staticmethod
    def _event_item(
        *,
        item_key: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "item",
            "item_key": item_key,
            "status": status,
        }
        if detail:
            payload["detail"] = detail
        return payload

    @staticmethod
    def _event_annotation(
        *,
        item_key: str,
        status: str,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "annotation",
            "item_key": item_key,
            "status": status,
        }
        if message:
            payload["message"] = message
        if detail:
            payload["detail"] = detail
        return payload

    @staticmethod
    def _event_warning(*, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "warning",
            "message": message,
        }
        if detail:
            payload["detail"] = detail
        return payload

    @staticmethod
    def _event_error(*, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "error",
            "message": message,
        }
        if detail:
            payload["detail"] = detail
        return payload

    @staticmethod
    def _event_complete(detail: dict[str, Any]) -> dict[str, Any]:
        return {
            "event": "complete",
            "detail": detail,
            "message": "import task completed",
        }


def manifest_dataset_id(manifest: dict[str, Any]) -> uuid.UUID:
    raw = manifest.get("dataset_id")
    if not raw:
        raise BadRequestAppException("Manifest missing dataset_id")
    return uuid.UUID(str(raw))
