"""
Annotation system modules for custom annotation interfaces.
Each annotation system type (e.g., satellite_fedo) has its own submodule.

This package provides:
- AnnotationSystemHandler: Base class for annotation system handlers
- HandlerRegistry: Registry for automatic handler discovery and retrieval
- ProgressTracker: Progress tracking for upload operations
"""

from .base import (
    AnnotationSystemHandler,
    EventType,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    UploadContext,
)
from .registry import (
    HandlerRegistry,
    register_handler,
    get_handler,
    discover_handlers,
)
from .progress import (
    ProgressTracker,
    AsyncProgressTracker,
    ProgressLog,
    ProgressLevel,
    create_tracker,
    get_tracker,
    remove_tracker,
)


__all__ = [
    # Base classes
    'AnnotationSystemHandler',
    'EventType',
    'ProcessResult',
    'ProgressCallback',
    'ProgressInfo',
    'UploadContext',
    # Registry
    'HandlerRegistry',
    'register_handler',
    'get_handler',
    'discover_handlers',
    # Progress
    'ProgressTracker',
    'AsyncProgressTracker',
    'ProgressLog',
    'ProgressLevel',
    'create_tracker',
    'get_tracker',
    'remove_tracker',
]


def init_handlers() -> None:
    """
    Initialize and register all annotation system handlers.
    Call this during application startup.
    """
    discover_handlers()
