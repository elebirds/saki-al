"""
Annotation Systems Module.

Provides a unified, pluggable architecture for different annotation systems.
Each system (CLASSIC, FEDO, etc.) has a single Handler that manages:

1. Upload & Processing - Transform raw files into annotatable samples
2. Annotation Sync - Real-time processing during annotation session
3. Batch Save - Pre-save hooks for validation/transformation

Directory Structure:
    annotation/
    ├── base.py          # AnnotationSystemHandler base class
    ├── registry.py      # Handler registration and discovery
    ├── progress.py      # Progress tracking utilities
    ├── handlers/        # Handler implementations
    │   ├── classic.py   # Standard image annotation
    │   └── fedo.py      # FEDO satellite data (dual-view)
    └── satellite_fedo/  # FEDO-specific processing utilities
        ├── processor.py # Data processing pipeline
        ├── parser.py    # Text file parsing
        ├── physics.py   # Physics calculations
        ├── visualizer.py # Image generation
        └── lookup.py    # Coordinate mapping tables

Usage:
    from saki_api.annotation import get_handler, discover_handlers
    
    # On app startup
    discover_handlers()
    
    # Get handler for a dataset's annotation system
    handler = get_handler(AnnotationSystemType.FEDO)
    
    # Process upload
    result = handler.process_upload(file_path, context)
    
    # Handle annotation sync
    sync_result = handler.on_annotation_create(...)
"""

from .base import (
    AnnotationSystemHandler,
    AnnotationContext,
    EventType,
    ProcessResult,
    ProgressCallback,
    ProgressInfo,
    SyncResult,
    UploadContext,
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
from .registry import (
    HandlerRegistry,
    register_handler,
    get_handler,
    discover_handlers,
)

__all__ = [
    # Base classes and data structures
    'AnnotationSystemHandler',
    'AnnotationContext',
    'EventType',
    'ProcessResult',
    'ProgressCallback',
    'ProgressInfo',
    'SyncResult',
    'UploadContext',
    # Registry
    'HandlerRegistry',
    'register_handler',
    'get_handler',
    'discover_handlers',
    # Progress tracking
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
