"""
Dataset Processing Module

This module handles the creation and processing of dataset samples.
It separates the data ingestion pipeline from annotation sync logic.

Key components:
- BaseDatasetProcessor: Abstract base class for data processors
- ProcessorRegistry: Singleton registry for processor instances
- Processors: Implementation for different dataset types (Classic, FEDO, etc.)
"""

from saki_api.modules.annotation.extensions.dataset_processing.base import (
    BaseDatasetProcessor,
    UploadContext,
    ProcessResult,
    ProgressInfo,
    ProgressCallback,
    EventType,
)
from saki_api.modules.annotation.extensions.dataset_processing.registry import (
    ProcessorRegistry,
    register_processor,
    get_processor,
)

__all__ = [
    # Base classes
    "BaseDatasetProcessor",
    "UploadContext",
    "ProcessResult",
    "ProgressInfo",
    "ProgressCallback",
    "EventType",
    # Registry
    "ProcessorRegistry",
    "register_processor",
    "get_processor",
]
