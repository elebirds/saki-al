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
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.annotation.extensions.dataset_processing.base import UploadContext, ProgressCallback, EventType, \
    ProgressInfo
from saki_api.modules.annotation.extensions.factory import AnnotationSystemFactory
from saki_api.modules.project.repo.sample import SampleRepository
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
