"""
Progress tracking and logging utilities for upload operations.
Provides SSE-compatible progress updates and structured logging.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProgressLevel(str, Enum):
    """Log level for progress messages."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ProgressLog:
    """A single progress log entry."""
    timestamp: str
    level: ProgressLevel
    stage: str
    message: str
    current: int = 0
    total: int = 0
    percentage: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "stage": self.stage,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "percentage": self.percentage,
            "details": self.details,
        }

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


class ProgressTracker:
    """
    Tracks progress for multi-file upload operations.
    
    Provides:
    - Progress percentage calculation
    - Structured logging
    - SSE-compatible event streaming
    - History of progress events
    
    Example:
        tracker = ProgressTracker(total_files=10)
        
        for i, file in enumerate(files):
            tracker.update(
                current=i + 1,
                stage="upload",
                message=f"Uploading {file.name}",
            )
            # ... process file ...
            tracker.file_complete(file.name, success=True)
        
        tracker.complete()
    """

    def __init__(
            self,
            total_files: int,
            callback: Optional[Callable[[ProgressLog], None]] = None,
            max_history: int = 100,
    ):
        """
        Initialize progress tracker.
        
        Args:
            total_files: Total number of files to process
            callback: Optional callback called for each progress update
            max_history: Maximum number of log entries to keep
        """
        self.total_files = total_files
        self.current_file = 0
        self.callback = callback
        self.max_history = max_history

        self._history: deque = deque(maxlen=max_history)
        self._start_time = time.time()
        self._file_results: List[Dict[str, Any]] = []
        self._current_stage = "init"
        self._is_complete = False

    def _now(self) -> str:
        """Get current ISO timestamp."""
        return datetime.utcnow().isoformat() + "Z"

    def _emit(self, log: ProgressLog) -> None:
        """Emit a progress log entry."""
        self._history.append(log)

        # Log to Python logger
        log_method = getattr(logger, log.level.value, logger.info)
        log_method(f"[{log.stage}] {log.current}/{log.total} ({log.percentage:.1f}%) - {log.message}")

        # Call callback if provided
        if self.callback:
            try:
                self.callback(log)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

    def update(
            self,
            current: int,
            stage: str,
            message: str,
            level: ProgressLevel = ProgressLevel.INFO,
            details: Optional[Dict[str, Any]] = None,
    ) -> ProgressLog:
        """
        Update progress.
        
        Args:
            current: Current file number (1-indexed)
            stage: Current processing stage
            message: Human-readable message
            level: Log level
            details: Additional details
            
        Returns:
            The created ProgressLog entry
        """
        self.current_file = current
        self._current_stage = stage

        percentage = (current / self.total_files * 100) if self.total_files > 0 else 0

        log = ProgressLog(
            timestamp=self._now(),
            level=level,
            stage=stage,
            message=message,
            current=current,
            total=self.total_files,
            percentage=round(percentage, 2),
            details=details or {},
        )

        self._emit(log)
        return log

    def file_start(self, filename: str, index: int) -> ProgressLog:
        """Log file processing start."""
        return self.update(
            current=index + 1,
            stage="processing",
            message=f"Processing: {filename}",
            details={"filename": filename, "action": "start"},
        )

    def file_complete(
            self,
            filename: str,
            success: bool,
            sample_id: Optional[str] = None,
            error: Optional[str] = None,
    ) -> ProgressLog:
        """Log file processing completion."""
        result = {
            "filename": filename,
            "success": success,
            "sample_id": sample_id,
            "error": error,
        }
        self._file_results.append(result)

        level = ProgressLevel.INFO if success else ProgressLevel.ERROR
        message = f"Completed: {filename}" if success else f"Failed: {filename} - {error}"

        return self.update(
            current=self.current_file,
            stage="processing",
            message=message,
            level=level,
            details={"filename": filename, "action": "complete", **result},
        )

    def log(
            self,
            message: str,
            level: ProgressLevel = ProgressLevel.INFO,
            details: Optional[Dict[str, Any]] = None,
    ) -> ProgressLog:
        """Log a message without changing progress."""
        log = ProgressLog(
            timestamp=self._now(),
            level=level,
            stage=self._current_stage,
            message=message,
            current=self.current_file,
            total=self.total_files,
            percentage=round(
                (self.current_file / self.total_files * 100) if self.total_files > 0 else 0, 2
            ),
            details=details or {},
        )
        self._emit(log)
        return log

    def complete(self) -> ProgressLog:
        """Mark the upload operation as complete."""
        self._is_complete = True
        elapsed = time.time() - self._start_time

        success_count = sum(1 for r in self._file_results if r["success"])
        error_count = len(self._file_results) - success_count

        return self.update(
            current=self.total_files,
            stage="complete",
            message=f"Upload complete: {success_count} succeeded, {error_count} failed",
            details={
                "action": "complete",
                "success_count": success_count,
                "error_count": error_count,
                "elapsed_seconds": round(elapsed, 2),
                "files_per_second": round(self.total_files / elapsed, 2) if elapsed > 0 else 0,
            },
        )

    def error(self, message: str, details: Optional[Dict[str, Any]] = None) -> ProgressLog:
        """Log an error."""
        return self.log(message, level=ProgressLevel.ERROR, details=details)

    def warning(self, message: str, details: Optional[Dict[str, Any]] = None) -> ProgressLog:
        """Log a warning."""
        return self.log(message, level=ProgressLevel.WARNING, details=details)

    @property
    def history(self) -> List[ProgressLog]:
        """Get all progress log entries."""
        return list(self._history)

    @property
    def results(self) -> Dict[str, Any]:
        """Get summary of file processing results."""
        success_count = sum(1 for r in self._file_results if r["success"])
        return {
            "total": self.total_files,
            "processed": len(self._file_results),
            "success": success_count,
            "errors": len(self._file_results) - success_count,
            "files": self._file_results,
            "is_complete": self._is_complete,
        }

    def to_sse_events(self) -> List[str]:
        """Convert history to SSE event strings."""
        return [log.to_sse() for log in self._history]


class AsyncProgressTracker(ProgressTracker):
    """
    Async version of ProgressTracker with SSE streaming support.
    
    Example:
        tracker = AsyncProgressTracker(total_files=10)
        
        async def sse_endpoint():
            async for event in tracker.stream():
                yield event
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._subscribers: List[asyncio.Queue] = []

    def _emit(self, log: ProgressLog) -> None:
        """Emit to all subscribers."""
        super()._emit(log)

        # Put in queue for async subscribers
        for queue in self._subscribers:
            try:
                queue.put_nowait(log)
            except asyncio.QueueFull:
                pass  # Skip if subscriber is too slow

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to progress updates."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from progress updates."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def stream(self) -> AsyncGenerator[str, None]:
        """
        Stream progress updates as SSE events.
        
        Yields:
            SSE-formatted event strings
        """
        queue = self.subscribe()
        try:
            while not self._is_complete:
                try:
                    log = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield log.to_sse()
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            self.unsubscribe(queue)


# Global tracker storage for active uploads
_active_trackers: Dict[str, ProgressTracker] = {}


def create_tracker(upload_id: str, total_files: int) -> ProgressTracker:
    """Create and register a progress tracker."""
    tracker = ProgressTracker(total_files=total_files)
    _active_trackers[upload_id] = tracker
    return tracker


def get_tracker(upload_id: str) -> Optional[ProgressTracker]:
    """Get an active progress tracker by ID."""
    return _active_trackers.get(upload_id)


def remove_tracker(upload_id: str) -> None:
    """Remove a progress tracker."""
    _active_trackers.pop(upload_id, None)
