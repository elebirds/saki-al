"""
Annotation Sync Module

This module handles real-time annotation synchronization for different dataset types.
It separates the sync logic from data ingestion pipeline.

Key components:
- BaseAnnotationSyncHandler: Abstract base class for sync handlers
- SyncHandlerRegistry: Singleton registry for sync handler instances
- Handlers: Implementation for different dataset types (NoOp, DualView, etc.)
"""

from saki_api.modules.annotation_sync.base import (
    BaseAnnotationSyncHandler,
    AnnotationContext,
    SyncResult,
)
from saki_api.modules.annotation_sync.registry import (
    SyncHandlerRegistry,
    register_sync_handler,
    get_sync_handler,
)

__all__ = [
    # Base classes
    "BaseAnnotationSyncHandler",
    "AnnotationContext",
    "SyncResult",
    # Registry
    "SyncHandlerRegistry",
    "register_sync_handler",
    "get_sync_handler",
]
