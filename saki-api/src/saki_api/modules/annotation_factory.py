"""
Annotation System Factory

Factory for creating AnnotationSystemFacade instances for different dataset types.
"""

import logging
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.models.enums import DatasetType
from saki_api.modules.annotation_system import AnnotationSystemFacade

logger = logging.getLogger(__name__)


class AnnotationSystemFactory:
    """
    Factory for creating annotation system facades.

    This factory creates AnnotationSystemFacade instances by combining
    the appropriate dataset processor and annotation sync handler for
    each dataset type.

    Example:
        # Get a facade for FEDO dataset
        facade = AnnotationSystemFactory.create_system(
            DatasetType.FEDO,
            session=db_session
        )

        # Use the facade
        result = await facade.process_upload(file, context)
        sync_result = facade.on_annotation_create(...)
    """

    @staticmethod
    def create_system(
            dataset_type: DatasetType,
            session: Optional[AsyncSession] = None,
    ) -> AnnotationSystemFacade:
        """
        Create an AnnotationSystemFacade for the given dataset type.

        Args:
            dataset_type: The dataset type (CLASSIC, FEDO, etc.)
            session: Optional database session for asset operations

        Returns:
            AnnotationSystemFacade instance

        Raises:
            NotFoundAppException: If processor or sync handler not found
        """
        from saki_api.modules.dataset_processing.registry import ProcessorRegistry
        from saki_api.modules.annotation_sync.registry import SyncHandlerRegistry

        processor_reg = ProcessorRegistry.get_instance()
        sync_reg = SyncHandlerRegistry.get_instance()

        try:
            processor = processor_reg.get(dataset_type, cached=False)
            # Re-initialize processor with session if provided
            if session:
                processor_class = processor.__class__
                processor = processor_class(session)
        except NotFoundAppException as e:
            logger.error(f"No processor found for dataset type: {dataset_type.value}")
            raise NotFoundAppException(
                f"No dataset processor found for type: {dataset_type.value}"
            ) from e

        try:
            sync_handler = sync_reg.get(dataset_type, cached=False)
            # Re-initialize sync handler with session if provided
            if session:
                handler_class = sync_handler.__class__
                sync_handler = handler_class(session)
        except NotFoundAppException:
            # If no sync handler is registered, use a default pass-through
            logger.warning(
                f"No sync handler found for dataset type: {dataset_type.value}, "
                f"using default pass-through behavior"
            )
            from saki_api.modules.annotation_sync.handlers.no_op import NoOpSyncHandler
            sync_handler = NoOpSyncHandler(session)

        return AnnotationSystemFacade(
            dataset_processor=processor,
            sync_handler=sync_handler,
        )

    @staticmethod
    def discover_all() -> None:
        """
        Discover and register all processors and sync handlers.

        Call this during application startup to ensure all handlers are registered.
        """
        from saki_api.modules.dataset_processing.registry import discover_processors
        from saki_api.modules.annotation_sync.registry import discover_sync_handlers

        discover_processors()
        discover_sync_handlers()

        logger.info("Discovered all annotation system processors and handlers")

    @staticmethod
    def list_available() -> dict:
        """
        List all available dataset types with their processors and handlers.

        Returns:
            Dict mapping dataset types to handler names
        """
        from saki_api.modules.dataset_processing.registry import ProcessorRegistry
        from saki_api.modules.annotation_sync.registry import SyncHandlerRegistry

        processor_reg = ProcessorRegistry.get_instance()
        sync_reg = SyncHandlerRegistry.get_instance()

        result = {}
        for dt in DatasetType:
            result[dt.value] = {
                "processor": processor_reg._handlers.get(dt).__name__ if dt in processor_reg._handlers else None,
                "sync_handler": sync_reg._handlers.get(dt).__name__ if dt in sync_reg._handlers else None,
            }

        return result
