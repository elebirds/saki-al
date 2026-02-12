"""
Sync handler registry for annotation sync handlers.

Provides automatic registration and retrieval of sync handlers.
"""

from typing import Dict, Optional, Type

from loguru import logger

from saki_api.modules.annotation.extensions.registry_base import HandlerRegistryMixin
from saki_api.modules.annotation.extensions.sync.base import BaseAnnotationSyncHandler
from saki_api.modules.shared.modeling.enums import DatasetType


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
    return SyncHandlerRegistry.get_instance().register(cls)  # type: ignore


def get_sync_handler(system_type: DatasetType) -> BaseAnnotationSyncHandler:
    """Get a handler instance for a dataset type."""
    return SyncHandlerRegistry.get_instance().get(system_type)  # type: ignore


def discover_sync_handlers() -> None:
    """
    Import all handler modules to trigger registration.
    Call during application startup.
    """
    import importlib

    handler_modules = [
        "saki_api.modules.annotation.extensions.sync.handlers.no_op",
        "saki_api.modules.annotation.extensions.sync.handlers.dual_view",
    ]

    for module_name in handler_modules:
        try:
            importlib.import_module(module_name)
            logger.info("已加载标注同步处理器模块 module={}", module_name)
        except ImportError as e:
            logger.warning("加载标注同步处理器模块失败 module={} error={}", module_name, e)
