"""
Processor registry for dataset processors.

Provides automatic registration and retrieval of processors.
"""

from typing import Dict, Optional, Type

from loguru import logger

from saki_api.modules.annotation.extensions.dataset_processing.base import BaseDatasetProcessor
from saki_api.modules.annotation.extensions.registry_base import HandlerRegistryMixin
from saki_api.modules.shared.modeling.enums import DatasetType


class ProcessorRegistry(HandlerRegistryMixin):
    """
    Registry for dataset processors.

    Processors can be registered via decorator or manually.

    Example:
        @register_processor
        class FedoProcessor(BaseDatasetProcessor):
            system_type = DatasetType.FEDO
            ...

        # Getting a processor
        processor = ProcessorRegistry.get_instance().get(DatasetType.FEDO)
    """

    _instance: Optional["ProcessorRegistry"] = None
    _handlers: Dict[DatasetType, Type[BaseDatasetProcessor]] = {}
    _cached_instances: Dict[DatasetType, BaseDatasetProcessor] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ProcessorRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# ============================================================================
# Module-level convenience functions
# ============================================================================

def register_processor(cls: Type[BaseDatasetProcessor]) -> Type[BaseDatasetProcessor]:
    """Decorator to register a processor class."""
    return ProcessorRegistry.get_instance().register(cls)  # type: ignore


def get_processor(system_type: DatasetType) -> BaseDatasetProcessor:
    """Get a processor instance for a dataset type."""
    return ProcessorRegistry.get_instance().get(system_type)  # type: ignore


def discover_processors() -> None:
    """
    Import all processor modules to trigger registration.
    Call during application startup.
    """
    import importlib

    processor_modules = [
        "saki_api.modules.annotation.extensions.dataset_processing.processors.classic",
        "saki_api.modules.annotation.extensions.dataset_processing.processors.fedo",
    ]

    for module_name in processor_modules:
        try:
            importlib.import_module(module_name)
            logger.info("已加载数据处理器模块 module={}", module_name)
        except ImportError as e:
            logger.warning("加载数据处理器模块失败 module={} error={}", module_name, e)
