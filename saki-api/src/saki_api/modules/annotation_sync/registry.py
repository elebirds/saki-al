"""
Sync handler registry for annotation sync handlers.

Provides automatic registration and retrieval of sync handlers.
"""

import logging
from typing import Dict, Optional, Type

from saki_api.models.enums import DatasetType
from saki_api.modules.annotation_sync.base import BaseAnnotationSyncHandler
from saki_api.modules.registry_base import HandlerRegistryMixin

logger = logging.getLogger(__name__)


class SyncHandlerRegistry(HandlerRegistryMixin):
    """
    Registry for annotation sync handlers.

    Handlers can be registered via decorator or manually.

    Example:
        @register_sync_handler
        class DualViewSyncHandler(BaseAnnotationSyncHandler):
            system_type = DatasetType.FEDO
            ...

        # Getting a handler
        handler = SyncHandlerRegistry.get_instance().get(DatasetType.FEDO)
    """

    _instance: Optional["SyncHandlerRegistry"] = None
    _handlers: Dict[DatasetType, Type[BaseAnnotationSyncHandler]] = {}
    _cached_instances: Dict[DatasetType, BaseAnnotationSyncHandler] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "SyncHandlerRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# ============================================================================
# Module-level convenience functions
# ============================================================================

def register_sync_handler(cls: Type[BaseAnnotationSyncHandler]) -> Type[BaseAnnotationSyncHandler]:
    """Decorator to register a handler class."""
    return SyncHandlerRegistry.get_instance().register(cls) # type: ignore


def get_sync_handler(system_type: DatasetType) -> BaseAnnotationSyncHandler:
    """Get a handler instance for a dataset type."""
    return SyncHandlerRegistry.get_instance().get(system_type) # type: ignore


def discover_sync_handlers() -> None:
    """
    Import all handler modules to trigger registration.
    Call during application startup.
    """
    import importlib

    handler_modules = [
        "saki_api.modules.annotation_sync.handlers.no_op",
        "saki_api.modules.annotation_sync.handlers.dual_view",
    ]

    for module_name in handler_modules:
        try:
            importlib.import_module(module_name)
            logger.info(f"Loaded sync handler: {module_name}")
        except ImportError as e:
            logger.warning(f"Could not load sync handler {module_name}: {e}")
