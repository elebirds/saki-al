"""
Base class for annotation system handlers.

Provides a unified, pluggable architecture for different annotation systems.
Each handler manages both:
- Data upload/processing pipeline
- Annotation sync/save operations

This is the SINGLE handler interface for annotation systems.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from saki_api.models.enums import AnnotationSystemType, AnnotationType, AnnotationSource

logger = logging.getLogger(__name__)


# ============================================================================
# Event System
# ============================================================================

class EventType(str, Enum):
    """Events that can be emitted by annotation system handlers."""
    # Upload/Processing events
    UPLOAD_START = "upload_start"
    UPLOAD_PROGRESS = "upload_progress"
    UPLOAD_COMPLETE = "upload_complete"
    PROCESS_START = "process_start"
    PROCESS_PROGRESS = "process_progress"
    PROCESS_COMPLETE = "process_complete"
    PROCESS_ERROR = "process_error"

    # Annotation events
    ANNOTATION_SYNC = "annotation_sync"
    ANNOTATION_SAVE = "annotation_save"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ProgressInfo:
    """Progress information for long-running operations."""
    current: int = 0
    total: int = 0
    percentage: float = 0.0
    message: str = ""
    stage: str = ""

    def update(self, current: int, message: str = "", stage: str = "") -> "ProgressInfo":
        """Update progress and return self for chaining."""
        self.current = current
        if self.total > 0:
            self.percentage = (current / self.total) * 100
        if message:
            self.message = message
        if stage:
            self.stage = stage
        return self


@dataclass
class UploadContext:
    """Context for upload/processing operations."""
    dataset_id: str
    upload_dir: Path
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessResult:
    """Result of processing a single uploaded file."""
    success: bool
    sample_id: Optional[str] = None
    filename: str = ""
    error: Optional[str] = None
    # Fields to set on the Sample model
    sample_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnnotationContext:
    """Context for annotation operations."""
    sample_id: str
    dataset_id: str
    sample_meta: Dict[str, Any] = field(default_factory=dict)
    annotator_id: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a single annotation sync action."""
    success: bool
    annotation_id: str
    action: str  # 'create', 'update', 'delete'
    error: Optional[str] = None
    # Auto-generated annotations (e.g., FEDO dual-view mapping)
    generated: List[Dict[str, Any]] = field(default_factory=list)


class ProgressCallback(Protocol):
    """Protocol for progress callback functions."""

    def __call__(self, event: EventType, progress: ProgressInfo) -> None: ...


# ============================================================================
# Base Handler Class
# ============================================================================

class AnnotationSystemHandler(ABC):
    """
    Abstract base class for annotation system handlers.
    
    Each annotation system (CLASSIC, FEDO, etc.) implements this interface
    to handle the complete lifecycle:
    
    1. Upload & Processing:
       - validate_file() - Check if file can be processed
       - process_upload() - Process uploaded file, create sample data
       
    2. Annotation Sync (real-time, during annotation session):
       - on_annotation_create() - Handle new annotation
       - on_annotation_update() - Handle annotation modification  
       - on_annotation_delete() - Handle annotation removal
       
    3. Batch Save (when user clicks Save):
       - on_batch_save() - Process annotations before persisting to DB
    
    Example:
        @register_handler
        class FedoHandler(AnnotationSystemHandler):
            system_type = AnnotationSystemType.FEDO
            
            def on_annotation_create(self, ...):
                # Generate dual-view mapped annotation
                return SyncResult(success=True, generated=[...])
    """

    # Class attribute: which annotation system this handler supports
    system_type: AnnotationSystemType

    def __init__(self):
        self._event_listeners: Dict[EventType, List[Callable]] = {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ==================== Event System ====================

    def emit(self, event: EventType, data: Any = None) -> None:
        """Emit an event to all registered listeners."""
        if event in self._event_listeners:
            for callback in self._event_listeners[event]:
                try:
                    callback(event, data)
                except Exception as e:
                    self.logger.error(f"Error in event listener for {event}: {e}")

    def on(self, event: EventType, callback: Callable) -> None:
        """Register an event listener."""
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(callback)

    # ==================== Upload & Processing ====================

    def pre_upload(self, context: UploadContext) -> None:
        """Hook called before upload batch starts."""
        self.emit(EventType.UPLOAD_START, {"dataset_id": context.dataset_id})

    def post_upload(self, context: UploadContext, results: List[ProcessResult]) -> None:
        """Hook called after upload batch completes."""
        success_count = sum(1 for r in results if r.success)
        self.emit(EventType.UPLOAD_COMPLETE, {
            "dataset_id": context.dataset_id,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
        })

    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """File extensions this handler can process (e.g., {'.jpg', '.png'})."""
        pass

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        """
        Validate if a file can be processed.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not file_path.exists():
            return False, "File does not exist"
        if file_path.suffix.lower() not in self.supported_extensions:
            return False, f"Unsupported file extension: {file_path.suffix}"
        return True, ""

    @abstractmethod
    def process_upload(
            self,
            file_path: Path,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process an uploaded file.
        
        Args:
            file_path: Path to the uploaded file
            context: Upload context with dataset info
            progress_callback: Optional progress callback
            
        Returns:
            ProcessResult with sample fields to save
        """
        pass

    # ==================== Annotation Sync (Real-time) ====================

    def on_annotation_create(
            self,
            annotation_id: str,
            label_id: str,
            ann_type: AnnotationType,
            data: Dict[str, Any],
            extra: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation creation during real-time sync.
        
        Override in subclasses for special processing (e.g., FEDO mapping).
        Default implementation: pass-through with no extra processing.
        
        Args:
            annotation_id: ID of the new annotation
            label_id: Label ID
            ann_type: Annotation type (rect, obb, polygon, etc.)
            data: Geometry data
            extra: System-specific extra data
            context: Annotation context
            
        Returns:
            SyncResult, with 'generated' list for auto-created annotations
        """
        return SyncResult(success=True, annotation_id=annotation_id, action="create")

    def on_annotation_update(
            self,
            annotation_id: str,
            label_id: Optional[str],
            ann_type: Optional[AnnotationType],
            data: Optional[Dict[str, Any]],
            extra: Optional[Dict[str, Any]],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation update during real-time sync.
        
        Override in subclasses for special processing.
        Default implementation: pass-through.
        """
        return SyncResult(success=True, annotation_id=annotation_id, action="update")

    def on_annotation_delete(
            self,
            annotation_id: str,
            extra: Dict[str, Any],
            context: AnnotationContext,
    ) -> SyncResult:
        """
        Handle annotation deletion during real-time sync.
        
        Override in subclasses for special processing.
        Default implementation: pass-through.
        
        Returns:
            SyncResult. For linked annotations (FEDO), include child IDs to delete
            in the 'generated' field with action='delete'.
        """
        return SyncResult(success=True, annotation_id=annotation_id, action="delete")

    # ==================== Batch Save ====================

    def on_batch_save(
            self,
            annotations: List[Dict[str, Any]],
            context: AnnotationContext,
    ) -> List[Dict[str, Any]]:
        """
        Process annotations before batch save to database.
        
        Override to modify, validate, or augment annotations.
        Default implementation: pass-through.
        
        Args:
            annotations: List of annotation dicts to save
            context: Annotation context
            
        Returns:
            Processed list of annotations
        """
        return annotations

    # ==================== Utilities ====================

    def generate_id(self) -> str:
        """Generate a unique annotation/sample ID."""
        return str(uuid.uuid4())

    def create_progress(self, total: int, message: str = "") -> ProgressInfo:
        """Create a new ProgressInfo instance."""
        return ProgressInfo(total=total, message=message)
