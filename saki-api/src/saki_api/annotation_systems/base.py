"""
Base class for annotation system handlers.
Provides a pluggable architecture for different annotation types.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from saki_api.models.enums import AnnotationSystemType

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Events that can be emitted by annotation system handlers."""
    # Upload events
    UPLOAD_START = "upload_start"
    UPLOAD_PROGRESS = "upload_progress"
    UPLOAD_FILE_START = "upload_file_start"
    UPLOAD_FILE_COMPLETE = "upload_file_complete"
    UPLOAD_FILE_ERROR = "upload_file_error"
    UPLOAD_COMPLETE = "upload_complete"

    # Processing events
    PROCESS_START = "process_start"
    PROCESS_PROGRESS = "process_progress"
    PROCESS_COMPLETE = "process_complete"
    PROCESS_ERROR = "process_error"

    # Annotation events
    ANNOTATION_START = "annotation_start"
    ANNOTATION_SAVE = "annotation_save"
    ANNOTATION_COMPLETE = "annotation_complete"


@dataclass
class ProgressInfo:
    """Progress information for long-running operations."""
    current: int = 0
    total: int = 0
    percentage: float = 0.0
    message: str = ""
    stage: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

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
class ProcessResult:
    """Result of processing a single file."""
    success: bool
    sample_id: Optional[str] = None
    filename: str = ""
    error: Optional[str] = None
    sample_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadContext:
    """Context information for upload operations."""
    project_id: str
    upload_dir: Path
    project_config: Dict[str, Any] = field(default_factory=dict)
    annotation_config: Dict[str, Any] = field(default_factory=dict)


class ProgressCallback(Protocol):
    """Protocol for progress callback functions."""

    def __call__(self, event: EventType, progress: ProgressInfo) -> None: ...


class AnnotationSystemHandler(ABC):
    """
    Abstract base class for annotation system handlers.
    
    Each annotation system type (CLASSIC, FEDO, etc.) should implement this
    interface to handle file uploads, processing, and annotation logic.
    
    Example:
        class FedoHandler(AnnotationSystemHandler):
            system_type = AnnotationSystemType.FEDO
            
            def process_upload(self, file_path, context, progress_callback):
                # Custom FEDO processing logic
                ...
    """

    # Class attribute: which annotation system this handler supports
    system_type: AnnotationSystemType

    def __init__(self):
        self._event_listeners: Dict[EventType, List[Callable]] = {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ==================== Event System ====================

    def on(self, event: EventType, callback: Callable) -> None:
        """Register an event listener."""
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(callback)

    def off(self, event: EventType, callback: Callable) -> None:
        """Remove an event listener."""
        if event in self._event_listeners:
            self._event_listeners[event] = [
                cb for cb in self._event_listeners[event] if cb != callback
            ]

    def emit(self, event: EventType, data: Any = None) -> None:
        """Emit an event to all registered listeners."""
        if event in self._event_listeners:
            for callback in self._event_listeners[event]:
                try:
                    callback(event, data)
                except Exception as e:
                    self.logger.error(f"Error in event listener for {event}: {e}")

    # ==================== Abstract Methods ====================

    @abstractmethod
    def process_upload(
            self,
            file_path: Path,
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process a single uploaded file.
        
        Args:
            file_path: Path to the uploaded file
            context: Upload context with project info and configs
            progress_callback: Optional callback for progress updates
            
        Returns:
            ProcessResult with success status and sample data
        """
        pass

    @abstractmethod
    def get_sample_fields(self, result: ProcessResult) -> Dict[str, Any]:
        """
        Get fields to set on the Sample model from processing result.
        
        Args:
            result: The processing result
            
        Returns:
            Dictionary of field names to values for Sample creation
        """
        pass

    # ==================== Optional Overrides ====================

    @property
    @abstractmethod
    def support_extensions(self) -> set[str]:
        pass

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        """
        Validate if a file can be processed by this handler.
        
        Args:
            file_path: Path to the file
            context: Upload context
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not file_path.exists():
            return False, "File does not exist"

        # Check file extension
        if file_path.suffix.lower() not in self.support_extensions:
            return False, f"Unsupported file extension: {file_path.suffix}"

        return True, ""

    def pre_upload(self, context: UploadContext) -> None:
        """Hook called before upload batch starts."""
        self.emit(EventType.UPLOAD_START, {"project_id": context.project_id})

    def post_upload(self, context: UploadContext, results: List[ProcessResult]) -> None:
        """Hook called after upload batch completes."""
        success_count = sum(1 for r in results if r.success)
        self.emit(EventType.UPLOAD_COMPLETE, {
            "project_id": context.project_id,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
        })

    def on_annotation_save(
            self,
            sample_id: str,
            annotation_data: Dict[str, Any],
            context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Hook called when annotation is saved.
        Override to add custom processing during annotation.
        
        Args:
            sample_id: ID of the sample being annotated
            annotation_data: The annotation data being saved
            context: Additional context
            
        Returns:
            Possibly modified annotation data
        """
        self.emit(EventType.ANNOTATION_SAVE, {
            "sample_id": sample_id,
            "annotation_data": annotation_data,
        })
        return annotation_data

    # ==================== Utility Methods ====================

    def create_progress(self, total: int, message: str = "") -> ProgressInfo:
        """Create a new ProgressInfo instance."""
        return ProgressInfo(total=total, message=message)

    def log_progress(self, progress: ProgressInfo) -> None:
        """Log progress information."""
        self.logger.info(
            f"[{progress.stage}] {progress.current}/{progress.total} "
            f"({progress.percentage:.1f}%) - {progress.message}"
        )
