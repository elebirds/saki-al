"""
Processor registry for dataset processors.

Provides automatic registration and retrieval of processors.
"""

import logging
from typing import Dict, Optional, Type

from saki_api.models.enums import DatasetType
from saki_api.modules.dataset_processing.base import BaseDatasetProcessor
from saki_api.modules.registry_base import HandlerRegistryMixin

logger = logging.getLogger(__name__)


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
    return ProcessorRegistry.get_instance().register(cls)


def get_processor(system_type: DatasetType) -> BaseDatasetProcessor:
    """Get a processor instance for a dataset type."""
    return ProcessorRegistry.get_instance().get(system_type)


def discover_processors() -> None:
    """
    Import all processor modules to trigger registration.
    Call during application startup.
    """
    import importlib

    processor_modules = [
        "saki_api.modules.dataset_processing.processors.classic",
        "saki_api.modules.dataset_processing.processors.fedo",
    ]

    for module_name in processor_modules:
        try:
            importlib.import_module(module_name)
            logger.info(f"Loaded processor: {module_name}")
        except ImportError as e:
            logger.warning(f"Could not load processor {module_name}: {e}")
