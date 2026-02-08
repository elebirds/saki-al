"""
Sample Service - Handles business logic for sample creation and file processing.

Manages sample creation workflow including:
- File upload processing via annotation system handlers
- Handler-based asset management
- Dataset type-specific handling
- Metadata extraction
"""

from loguru import logger
import uuid
from typing import Any, AsyncIterator, List, Optional

from fastapi import UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException
from saki_api.models.enums import DatasetType
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
from saki_api.modules.annotation_factory import AnnotationSystemFactory
from saki_api.modules.dataset_processing.base import UploadContext, ProgressCallback, EventType, ProgressInfo
from saki_api.repositories.sample import SampleRepository
from saki_api.schemas.sample import SampleRead
from saki_api.services.base import BaseService



class SampleService(BaseService[Sample, SampleRepository, SampleRead, SampleRead]):
    """
    Service for managing Samples and their Assets.
    
    Delegates upload processing to annotation system handlers:
    - CLASSIC: One image file = one sample with single asset
    - FEDO: One TXT file = one sample with multiple generated assets
    
    Handlers manage asset upload and return asset information,
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

    def _build_upload_context(
            self,
            dataset_id: uuid.UUID
    ) -> UploadContext:
        """
        Build upload context for handler processing.
        
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
            upload_context: UploadContext
    ):
        """
        Validate uploaded file using processor.

        Args:
            file: Uploaded file
            facade: AnnotationSystemFacade instance
            upload_context: Upload context

        Raises:
            BadRequestAppException: If validation fails
        """
        from pathlib import Path

        is_valid, error_msg = facade.dataset_processor.validate_file(
            Path(file.filename or "unknown"),
            upload_context
        )
        if not is_valid:
            logger.error("文件校验失败 error={}", error_msg)
            raise BadRequestAppException(f"File validation failed: {error_msg}")

    async def _process_single_file(
            self,
            file: UploadFile,
            facade,
            upload_context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None
    ):
        """
        Process a single file using processor.

        Args:
            file: Uploaded file
            facade: AnnotationSystemFacade instance
            upload_context: Upload context
            progress_callback: Optional progress callback for streaming updates

        Returns:
            ProcessResult from processor

        Raises:
            BadRequestAppException: If processing fails
        """
        process_result = await facade.dataset_processor.process_upload(
            file,
            upload_context,
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
        Process a batch of uploaded files.
        
        Delegates to appropriate handler based on dataset type:
        - CLASSIC: One file = one sample
        - FEDO: One file = one sample (with generated assets)
        
        Each handler automatically loads its configuration from environment/config files.
        
        Args:
            dataset: The dataset record
            files: List of uploaded files
            
        Returns:
            List of created sample records
            
        Raises:
            BadRequestAppException: If upload fails
        """
        created_samples = []
        logger.info(
            "开始批量处理数据集文件 dataset_id={} dataset_type={} file_count={}",
            dataset.id,
            dataset.type,
            len(files),
        )

        # Initialize facade and upload context
        facade = self._initialize_handler(dataset.type)
        upload_context = self._build_upload_context(dataset.id)

        # Process each file
        for file in files:
            try:
                logger.debug("开始处理文件 filename={}", file.filename)

                # Validate file
                await self._validate_file(file, facade, upload_context)

                # Process file via processor
                process_result = await self._process_single_file(file, facade, upload_context)

                # Create sample record
                created_sample = await self._create_sample_from_result(dataset.id, process_result)
                created_samples.append(created_sample)

            except Exception as e:
                logger.exception("处理文件失败 filename={} error={}", file.filename, e)
                raise BadRequestAppException(f"Failed to process file {file.filename}: {str(e)}")

        logger.info("批量处理完成，成功创建样本数量={}", len(created_samples))
        return created_samples

    async def process_single_file_with_progress(
            self,
            dataset: Dataset,
            file: UploadFile,
            progress_callback: Optional[ProgressCallback] = None
    ) -> SampleRead:
        """
        Process a single uploaded file with progress callback support.
        
        This method is designed for streaming upload endpoints that need
        real-time progress updates.
        
        Each handler automatically loads its configuration from environment/config files.
        
        Args:
            dataset: The dataset record
            file: Uploaded file
            progress_callback: Optional callback for progress updates
            
        Returns:
            Created sample record
            
        Raises:
            BadRequestAppException: If upload fails
        """
        logger.info(
            "开始处理单文件 dataset_id={} dataset_type={} filename={}",
            dataset.id,
            dataset.type,
            file.filename,
        )

        # Initialize facade and upload context
        facade = self._initialize_handler(dataset.type)
        upload_context = self._build_upload_context(dataset.id)

        try:
            # Validate file
            await self._validate_file(file, facade, upload_context)

            # Process file via processor with progress callback
            process_result = await self._process_single_file(
                file,
                facade,
                upload_context,
                progress_callback=progress_callback
            )

            # Create sample record
            created_sample = await self._create_sample_from_result(dataset.id, process_result)
            logger.info("单文件处理成功，样本已创建 sample_id={}", created_sample.id)
            return created_sample

        except Exception as e:
            logger.exception("单文件处理失败 filename={} error={}", file.filename, e)
            raise BadRequestAppException(f"Failed to process file {file.filename}: {str(e)}")

    async def iter_upload_progress_events(
            self,
            *,
            dataset: Dataset,
            files: List[UploadFile],
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream upload progress events for a batch of files.
        """
        results: list[dict[str, Any]] = []
        yield {"event": "start", "total": len(files)}

        facade = self._initialize_handler(dataset.type)
        upload_context = self._build_upload_context(dataset.id)

        for index, file in enumerate(files):
            filename = file.filename or ""
            yield {"event": "file_start", "index": index, "filename": filename}

            progress_events: list[dict[str, Any]] = []

            def progress_callback(event_type: EventType, progress: ProgressInfo):
                del event_type
                progress_events.append(
                    {
                        "event": "progress",
                        "file_index": index,
                        "filename": filename,
                        "stage": progress.stage,
                        "message": progress.message,
                        "percentage": progress.percentage,
                        "current": progress.current,
                        "total": progress.total,
                    }
                )

            created_sample: SampleRead | None = None
            processing_error: Exception | None = None
            try:
                await self._validate_file(file, facade, upload_context)
                process_result = await self._process_single_file(
                    file,
                    facade,
                    upload_context,
                    progress_callback=progress_callback,
                )
                created_sample = await self._create_sample_from_result(dataset.id, process_result)
            except Exception as exc:
                processing_error = exc
                logger.exception("文件上传失败 filename={} error={}", filename, exc)

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
                yield {
                    "event": "file_complete",
                    "index": index,
                    "filename": filename,
                    "success": True,
                    "sample_id": str(created_sample.id),
                }
            else:
                error_text = str(processing_error) if processing_error is not None else "unknown error"
                results.append(
                    {
                        "filename": filename,
                        "status": "error",
                        "error": error_text,
                    }
                )
                yield {
                    "event": "file_error",
                    "index": index,
                    "filename": filename,
                    "error": error_text,
                }

        success_count = sum(1 for item in results if item.get("status") == "success")
        error_count = len(results) - success_count
        yield {
            "event": "complete",
            "uploaded": success_count,
            "errors": error_count,
            "results": results,
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
