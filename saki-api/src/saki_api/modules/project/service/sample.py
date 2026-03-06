"""
Sample Service - Handles business logic for sample creation and file processing.

Manages sample creation workflow including:
- File processing via annotation system handlers
- Handler-based asset management
- Dataset type-specific handling
- Metadata extraction
"""

import uuid
from typing import Any, AsyncIterator, List, Optional

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import (
    BadRequestAppException,
    ConflictAppException,
    ForbiddenAppException,
    NotFoundAppException,
)
from saki_api.infra.cache.redis import get_redis_client
from saki_api.infra.db.transaction import transactional
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.annotation.extensions.dataset_processing.base import UploadContext, ProgressCallback, EventType, \
    ProgressInfo
from saki_api.modules.annotation.extensions.factory import AnnotationSystemFactory
from saki_api.modules.project.repo.sample import SampleRepository
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.shared.application.crud_service import CrudServiceBase
from saki_api.modules.shared.modeling.enums import DatasetType
from saki_api.modules.storage.api.sample import SampleRead
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


class SampleService(CrudServiceBase[Sample, SampleRepository, SampleRead, SampleRead]):
    """
    Service for managing Samples and their Assets.
    
    Delegates file processing to annotation system handlers:
    - CLASSIC: One image file = one sample with single asset
    - FEDO: One TXT file = one sample with multiple generated assets

    Handlers manage asset persistence and return asset information,
    which SampleService uses to build the Sample model.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Sample, SampleRepository, session)

    def _initialize_handler(self, dataset_type: DatasetType):
        """
        Get annotation system facade for dataset type.

        Args:
            dataset_type: Type of dataset

        Returns:
            AnnotationSystemFacade instance

        Raises:
            BadRequestAppException: If no handler found for dataset type
        """
        facade = AnnotationSystemFactory.create_system(dataset_type, self.session)
        return facade

    def _build_processing_context(
            self,
            dataset_id: uuid.UUID
    ) -> UploadContext:
        """
        Build processing context for handler processing.
        
        Args:
            dataset_id: Dataset UUID
            
        Returns:
            UploadContext instance
        """
        from pathlib import Path

        # Config with in_memory flag (handlers will load their own configs)
        config = {"in_memory": True}

        return UploadContext(
            dataset_id=str(dataset_id),
            upload_dir=Path("/tmp/uploads"),  # Temporary placeholder (not used for object storage)
            config=config
        )

    async def _validate_file(
            self,
            file: UploadFile,
            facade,
            process_context: UploadContext
    ):
        """
        Validate uploaded file using processor.

        Args:
            file: Uploaded file
            facade: AnnotationSystemFacade instance
            process_context: Processing context

        Raises:
            BadRequestAppException: If validation fails
        """
        from pathlib import Path

        is_valid, error_msg = facade.dataset_processor.validate_file(
            Path(file.filename or "unknown"),
            process_context
        )
        if not is_valid:
            logger.error("文件校验失败 error={}", error_msg)
            raise BadRequestAppException(f"File validation failed: {error_msg}")

    async def _validate_sample_name_policy(
            self,
            *,
            dataset: Dataset,
            filename: str | None,
    ) -> str:
        """
        Validate dataset duplicate-name policy for one uploaded sample.

        Returns normalized sample name when valid.
        """
        sample_name = (filename or "unknown").strip()
        if not sample_name:
            sample_name = "unknown"

        if dataset.allow_duplicate_sample_names:
            return sample_name

        exists = await self.repository.name_exists_in_dataset(dataset.id, sample_name)
        if exists:
            raise BadRequestAppException(
                f"Sample name already exists in dataset: {sample_name}"
            )
        return sample_name

    async def _process_single_file(
            self,
            file: UploadFile,
            facade,
            process_context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None
    ):
        """
        Process a single file using processor.

        Args:
            file: Uploaded file
            facade: AnnotationSystemFacade instance
            process_context: Processing context
            progress_callback: Optional progress callback for streaming updates

        Returns:
            ProcessResult from processor

        Raises:
            BadRequestAppException: If processing fails
        """
        process_result = await facade.dataset_processor.process_upload(
            file,
            process_context,
            progress_callback=progress_callback
        )

        if not process_result.success:
            raise BadRequestAppException(f"File processing failed: {process_result.error}")

        return process_result

    async def _create_sample_from_result(
            self,
            dataset_id: uuid.UUID,
            process_result
    ) -> SampleRead:
        """
        Create sample record from handler process result.
        
        Args:
            dataset_id: Dataset UUID
            process_result: ProcessResult from handler
            
        Returns:
            Created sample record
        """
        # Create sample with asset information
        sample = Sample(
            dataset_id=dataset_id,
            name=process_result.filename,
            asset_group=process_result.asset_ids,  # Maps roles to asset IDs
            primary_asset_id=uuid.UUID(process_result.primary_asset_id) if process_result.primary_asset_id else None,
            meta_info=process_result.sample_fields.get("meta_info", {})
        )

        # Merge sample_fields into meta_info if provided
        if "meta_info" in process_result.sample_fields:
            sample.meta_info.update(process_result.sample_fields["meta_info"])

        created_sample = await self.repository.create(sample.model_dump())
        logger.debug("已创建样本 sample_id={}", created_sample.id)

        return SampleRead.model_validate(created_sample)

    async def process_upload(
            self,
            dataset: Dataset,
            files: List[UploadFile]
    ) -> List[SampleRead]:
        """
        Process a batch of uploaded files and return created samples.
        """
        created_samples: List[SampleRead] = []
        logger.info(
            "开始批量处理数据集文件 dataset_id={} dataset_type={} file_count={}",
            dataset.id,
            dataset.type,
            len(files),
        )

        facade = self._initialize_handler(dataset.type)
        process_context = self._build_processing_context(dataset.id)

        for file in files:
            filename = file.filename or "unknown"
            try:
                await self._validate_sample_name_policy(dataset=dataset, filename=filename)
                await self._validate_file(file, facade, process_context)
                process_result = await self._process_single_file(file, facade, process_context)
                created_sample = await self._create_sample_from_result(dataset.id, process_result)
                created_samples.append(created_sample)
            except BadRequestAppException as exc:
                raise BadRequestAppException(
                    f"Failed to process file {filename}: {exc}"
                ) from exc
            except Exception as exc:
                logger.exception("处理文件失败 filename={} error={}", filename, exc)
                raise BadRequestAppException(
                    f"Failed to process file {filename}: {exc}"
                ) from exc

        logger.info("批量处理完成，成功创建样本数量={}", len(created_samples))
        return created_samples

    async def process_single_file_with_progress(
            self,
            dataset: Dataset,
            file: UploadFile,
            progress_callback: Optional[ProgressCallback] = None
    ) -> SampleRead:
        """
        Process a single uploaded file and emit processor progress via callback.
        """
        filename = file.filename or "unknown"
        logger.info(
            "开始处理单文件 dataset_id={} dataset_type={} filename={}",
            dataset.id,
            dataset.type,
            filename,
        )

        facade = self._initialize_handler(dataset.type)
        process_context = self._build_processing_context(dataset.id)
        try:
            await self._validate_sample_name_policy(dataset=dataset, filename=filename)
            await self._validate_file(file, facade, process_context)
            process_result = await self._process_single_file(
                file,
                facade,
                process_context,
                progress_callback=progress_callback,
            )
            created_sample = await self._create_sample_from_result(dataset.id, process_result)
            logger.info("单文件处理成功，样本已创建 sample_id={}", created_sample.id)
            return created_sample
        except BadRequestAppException as exc:
            raise BadRequestAppException(
                f"Failed to process file {filename}: {exc}"
            ) from exc
        except Exception as exc:
            logger.exception("单文件处理失败 filename={} error={}", filename, exc)
            raise BadRequestAppException(
                f"Failed to process file {filename}: {exc}"
            ) from exc

    @staticmethod
    def _build_progress_event(
            *,
            index: int,
            filename: str,
            progress: ProgressInfo,
    ) -> dict[str, Any]:
        return {
            "event": "progress",
            "file_index": index,
            "filename": filename,
            "stage": progress.stage,
            "message": progress.message,
            "percentage": progress.percentage,
            "current": progress.current,
            "total": progress.total,
        }

    async def _process_single_file_with_collected_progress(
            self,
            *,
            dataset: Dataset,
            file: UploadFile,
            index: int,
            facade,
            process_context: UploadContext,
    ) -> tuple[SampleRead | None, Exception | None, list[dict[str, Any]]]:
        filename = file.filename or ""
        progress_events: list[dict[str, Any]] = []

        def progress_callback(event_type: EventType, progress: ProgressInfo):
            del event_type
            progress_events.append(
                self._build_progress_event(
                    index=index,
                    filename=filename,
                    progress=progress,
                )
            )

        created_sample: SampleRead | None = None
        processing_error: Exception | None = None
        try:
            await self._validate_sample_name_policy(dataset=dataset, filename=filename)
            await self._validate_file(file, facade, process_context)
            process_result = await self._process_single_file(
                file,
                facade,
                process_context,
                progress_callback=progress_callback,
            )
            created_sample = await self._create_sample_from_result(dataset.id, process_result)
        except BadRequestAppException as exc:
            processing_error = exc
        except Exception as exc:
            processing_error = exc
            logger.exception("文件上传失败 filename={} error={}", filename, exc)

        return created_sample, processing_error, progress_events

    @staticmethod
    def _build_sample_complete_event(
            *,
            index: int,
            filename: str,
            sample_id: str,
    ) -> dict[str, Any]:
        return {
            "event": "sample_complete",
            "index": index,
            "filename": filename,
            "success": True,
            "sample_id": sample_id,
        }

    @staticmethod
    def _build_sample_error_event(
            *,
            index: int,
            filename: str,
            error: str,
    ) -> dict[str, Any]:
        return {
            "event": "sample_error",
            "index": index,
            "filename": filename,
            "error": error,
        }

    @staticmethod
    def _build_file_complete_event(
            *,
            index: int,
            filename: str,
            sample_id: str,
    ) -> dict[str, Any]:
        return {
            "event": "file_complete",
            "index": index,
            "filename": filename,
            "success": True,
            "sample_id": sample_id,
        }

    @staticmethod
    def _build_file_error_event(
            *,
            index: int,
            filename: str,
            error: str,
    ) -> dict[str, Any]:
        return {
            "event": "file_error",
            "index": index,
            "filename": filename,
            "error": error,
        }

    @staticmethod
    def _build_complete_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        success_count = sum(1 for item in results if item.get("status") == "success")
        error_count = len(results) - success_count
        return {
            "event": "complete",
            "uploaded": success_count,
            "errors": error_count,
            "results": results,
        }

    async def iter_upload_progress_events(
            self,
            *,
            dataset: Dataset,
            files: List[UploadFile],
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream legacy file-upload events for dataset streaming upload.
        """
        results: list[dict[str, Any]] = []
        yield {"event": "start", "total": len(files)}

        facade = self._initialize_handler(dataset.type)
        process_context = self._build_processing_context(dataset.id)

        for index, file in enumerate(files):
            filename = file.filename or ""
            yield {"event": "file_start", "index": index, "filename": filename}
            created_sample, processing_error, progress_events = await self._process_single_file_with_collected_progress(
                dataset=dataset,
                file=file,
                index=index,
                facade=facade,
                process_context=process_context,
            )

            for event in progress_events:
                yield event

            if processing_error is None and created_sample is not None:
                results.append(
                    {
                        "id": str(created_sample.id),
                        "filename": filename,
                        "status": "success",
                    }
                )
                yield self._build_file_complete_event(
                    index=index,
                    filename=filename,
                    sample_id=str(created_sample.id),
                )
            else:
                error_text = str(processing_error) if processing_error is not None else "unknown error"
                results.append(
                    {
                        "filename": filename,
                        "status": "error",
                        "error": error_text,
                    }
                )
                yield self._build_file_error_event(
                    index=index,
                    filename=filename,
                    error=error_text,
                )

        yield self._build_complete_summary(results)

    async def iter_sample_process_events(
            self,
            *,
            dataset: Dataset,
            files: List[UploadFile],
            facade=None,
            process_context: UploadContext | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream sample processing events for a batch of files.
        """
        facade = facade or self._initialize_handler(dataset.type)
        process_context = process_context or self._build_processing_context(dataset.id)

        for index, file in enumerate(files):
            filename = file.filename or ""
            created_sample, processing_error, progress_events = await self._process_single_file_with_collected_progress(
                dataset=dataset,
                file=file,
                index=index,
                facade=facade,
                process_context=process_context,
            )

            for event in progress_events:
                yield event

            if processing_error is None and created_sample is not None:
                yield self._build_sample_complete_event(
                    index=index,
                    filename=filename,
                    sample_id=str(created_sample.id),
                )
            else:
                error_text = str(processing_error) if processing_error is not None else "unknown error"
                yield self._build_sample_error_event(
                    index=index,
                    filename=filename,
                    error=error_text,
                )

    @staticmethod
    def _parse_scalar_count(value: Any) -> int:
        if isinstance(value, (tuple, list)):
            if not value:
                return 0
            value = value[0]
        return int(value or 0)

    async def _count_rows_by_sample(self, model, sample_id: uuid.UUID) -> int:
        row = (
            await self.session.exec(
                select(func.count()).select_from(model).where(model.sample_id == sample_id)
            )
        ).one()
        return self._parse_scalar_count(row)

    async def _collect_project_ids_by_sample(self, sample_id: uuid.UUID) -> list[str]:
        project_ids: set[str] = set()
        model_and_column = (
            (Annotation, Annotation.project_id),
            (CommitAnnotationMap, CommitAnnotationMap.project_id),
            (CommitSampleState, CommitSampleState.project_id),
        )
        for model, project_column in model_and_column:
            rows = await self.session.exec(
                select(project_column).where(model.sample_id == sample_id).distinct()
            )
            for item in rows.all():
                project_id = item[0] if isinstance(item, (tuple, list)) else item
                if project_id:
                    project_ids.add(str(project_id))
        return sorted(project_ids)

    async def _scan_working_snapshot_keys(self, sample_id: uuid.UUID) -> list[str]:
        pattern = f"{settings.REDIS_KEY_PREFIX}:working:*:*:*:{sample_id}"
        redis = get_redis_client()
        keys: list[str] = []
        try:
            async for key in redis.scan_iter(match=pattern, count=500):
                keys.append(str(key))
        except Exception as exc:
            logger.warning("扫描 Working 快照失败 sample_id={} error={}", sample_id, exc)
            return []
        return keys

    async def _inspect_sample_refs(self, sample_id: uuid.UUID) -> dict[str, Any]:
        annotation_count = await self._count_rows_by_sample(Annotation, sample_id)
        camap_count = await self._count_rows_by_sample(CommitAnnotationMap, sample_id)
        sample_state_count = await self._count_rows_by_sample(CommitSampleState, sample_id)
        draft_count = await self._count_rows_by_sample(AnnotationDraft, sample_id)
        candidate_count = await self._count_rows_by_sample(TaskCandidateItem, sample_id)
        working_keys = await self._scan_working_snapshot_keys(sample_id)
        project_ids = await self._collect_project_ids_by_sample(sample_id)

        committed_refs = {
            "annotation": annotation_count,
            "commit_annotation_map": camap_count,
            "commit_sample_state": sample_state_count,
            "project_ids": project_ids,
        }
        transient_refs = {
            "annotation_draft": draft_count,
            "step_candidate_item": candidate_count,
            "working_snapshots": len(working_keys),
        }
        has_committed_refs = (
            annotation_count > 0 or camap_count > 0 or sample_state_count > 0
        )
        return {
            "committed_refs": committed_refs,
            "transient_refs": transient_refs,
            "has_committed_refs": has_committed_refs,
        }

    async def _delete_rows_for_sample(self, model, sample_id: uuid.UUID) -> int:
        rows = await self.session.exec(select(model).where(model.sample_id == sample_id))
        items = list(rows.all())
        for item in items:
            await self.session.delete(item)
        if items:
            await self.session.flush()
        return len(items)

    async def _cleanup_working_snapshots(self, sample_id: uuid.UUID) -> int:
        keys = await self._scan_working_snapshot_keys(sample_id)
        if not keys:
            return 0
        redis = get_redis_client()
        try:
            deleted = await redis.delete(*keys)
            return int(deleted or 0)
        except Exception as exc:
            logger.warning("清理 Working 快照失败 sample_id={} error={}", sample_id, exc)
            return 0

    async def _cleanup_sample_refs(self, sample_id: uuid.UUID) -> dict[str, dict[str, int]]:
        committed_deleted = {
            "annotation": 0,
            "commit_annotation_map": 0,
            "commit_sample_state": 0,
        }
        transient_deleted = {
            "annotation_draft": 0,
            "step_candidate_item": 0,
            "working_snapshots": 0,
        }

        # FK 顺序：先删除依赖 annotation/sample 的映射，再删 annotation，再删 sample。
        committed_deleted["commit_annotation_map"] = await self._delete_rows_for_sample(
            CommitAnnotationMap,
            sample_id,
        )
        committed_deleted["commit_sample_state"] = await self._delete_rows_for_sample(
            CommitSampleState,
            sample_id,
        )
        transient_deleted["annotation_draft"] = await self._delete_rows_for_sample(
            AnnotationDraft,
            sample_id,
        )
        committed_deleted["annotation"] = await self._delete_rows_for_sample(
            Annotation,
            sample_id,
        )
        transient_deleted["step_candidate_item"] = await self._delete_rows_for_sample(
            TaskCandidateItem,
            sample_id,
        )
        transient_deleted["working_snapshots"] = await self._cleanup_working_snapshots(
            sample_id,
        )
        return {
            "committed_refs_deleted": committed_deleted,
            "transient_refs_deleted": transient_deleted,
        }

    async def _can_force_delete(self, actor_user_id: uuid.UUID, dataset_owner_id: uuid.UUID) -> bool:
        if actor_user_id == dataset_owner_id:
            return True
        checker = PermissionChecker(self.session)
        return await checker.is_super_admin(actor_user_id)

    @staticmethod
    def _build_conflict_payload(ref_summary: dict[str, Any], can_force: bool) -> dict[str, Any]:
        return {
            "reason": "sample_in_use",
            "confirmation_required": True,
            "can_force": can_force,
            "committed_refs": ref_summary["committed_refs"],
            "transient_refs": ref_summary["transient_refs"],
        }

    @transactional
    async def delete_sample_with_policy(
            self,
            *,
            dataset_id: uuid.UUID,
            sample_id: uuid.UUID,
            actor_user_id: uuid.UUID,
            force: bool = False,
    ) -> dict[str, Any]:
        sample_result = await self.session.exec(
            select(Sample).where(Sample.id == sample_id).with_for_update()
        )
        sample = sample_result.first()
        if not sample:
            raise NotFoundAppException(f"Sample {sample_id} not found")
        if sample.dataset_id != dataset_id:
            raise BadRequestAppException("Sample not found in dataset")

        dataset = await self.session.get(Dataset, dataset_id)
        if not dataset:
            raise NotFoundAppException(f"Dataset {dataset_id} not found")

        ref_summary = await self._inspect_sample_refs(sample_id)
        has_committed_refs = bool(ref_summary["has_committed_refs"])
        can_force = await self._can_force_delete(actor_user_id, dataset.owner_id)

        if has_committed_refs and not force:
            raise ConflictAppException(
                "Sample is referenced by committed data, confirmation required before force delete",
                data=self._build_conflict_payload(ref_summary, can_force=can_force),
            )
        if has_committed_refs and force and not can_force:
            raise ForbiddenAppException("Force delete requires dataset owner or super admin")

        forced = bool(force and has_committed_refs)
        try:
            cleanup = await self._cleanup_sample_refs(sample_id)
            await self.session.delete(sample)
            await self.session.flush()
        except IntegrityError as exc:
            logger.warning("样本删除冲突 sample_id={} error={}", sample_id, exc)
            raise ConflictAppException(
                "Sample is still referenced and cannot be deleted directly",
                data=self._build_conflict_payload(ref_summary, can_force=can_force),
            ) from exc

        return {
            "ok": True,
            "forced": forced,
            "message": "Sample deleted successfully",
            "cleanup": cleanup,
        }

    async def get_asset_for_sample(
            self,
            sample_id: uuid.UUID,
            asset_key: str = "image_main"
    ) -> Optional[uuid.UUID]:
        """
        Get a specific asset ID from a sample's asset_group.
        
        Args:
            sample_id: Sample UUID
            asset_key: Asset group key (e.g., "image_main", "raw_text")
            
        Returns:
            Asset UUID if found, None otherwise
            
        Raises:
            Exception: If sample not found
        """
        sample = await self.get_by_id_or_raise(sample_id)

        if not sample.asset_group or asset_key not in sample.asset_group:
            return None

        try:
            return uuid.UUID(sample.asset_group[asset_key])
        except (ValueError, TypeError):
            logger.error(
                "样本中的资产 ID 无效 sample_id={} asset_key={} asset_id={}",
                sample_id,
                asset_key,
                sample.asset_group.get(asset_key),
            )
            return None

    async def get_all_assets_for_sample(
            self,
            sample_id: uuid.UUID
    ) -> List[uuid.UUID]:
        """
        Get all asset IDs from a sample's asset_group.
        
        Args:
            sample_id: Sample UUID
            
        Returns:
            List of asset UUIDs
        """
        sample = await self.get_by_id_or_raise(sample_id)

        if not sample.asset_group:
            return []

        asset_ids = []
        for asset_id_str in sample.asset_group.values():
            try:
                asset_ids.append(uuid.UUID(asset_id_str))
            except (ValueError, TypeError):
                logger.warning("样本中的资产 ID 无效 sample_id={} asset_id={}", sample_id, asset_id_str)

        return asset_ids

    async def get_primary_asset_for_sample(
            self,
            sample_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        """
        Get the primary asset (for display) of a sample.
        
        Args:
            sample_id: Sample UUID
            
        Returns:
            Primary asset UUID if set, None otherwise
        """
        sample = await self.get_by_id_or_raise(sample_id)
        return sample.primary_asset_id
