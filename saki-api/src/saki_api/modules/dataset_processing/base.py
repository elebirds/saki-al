"""
Base class for dataset processors.

Provides a unified interface for processing uploaded files and creating
dataset samples. Each processor handles a specific dataset type (CLASSIC, FEDO, etc.)

This module is responsible for:
- Data upload and processing pipeline
- Asset management (via AssetService)
- Progress tracking and event emission
"""

from loguru import logger
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Protocol

from saki_api.models.enums import DatasetType

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession
    from saki_api.services.storage.asset import AssetService
    from fastapi import UploadFile



# ============================================================================
# Event System
# ============================================================================

class EventType(str, Enum):
    """Events that can be emitted by dataset processors."""
    # Upload/Processing events
    UPLOAD_START = "upload_start"
    UPLOAD_PROGRESS = "upload_progress"
    UPLOAD_COMPLETE = "upload_complete"
    PROCESS_START = "process_start"
    PROCESS_PROGRESS = "process_progress"
    PROCESS_COMPLETE = "process_complete"
    PROCESS_ERROR = "process_error"


class ProcessingStage(str, Enum):
    """Processing stages for progress tracking."""
    # Classic handler stages
    CLASSIC_UPLOAD = "classic_upload"
    CLASSIC_METADATA = "classic_metadata"
    CLASSIC_COMPLETE = "classic_complete"

    # FEDO handler stages
    FEDO_UPLOAD_RAW = "fedo_upload_raw"
    FEDO_PARSE = "fedo_parse"
    FEDO_PHYSICS = "fedo_physics"
    FEDO_VIZ = "fedo_viz"
    FEDO_UPLOAD_ASSETS = "fedo_upload_assets"
    FEDO_COMPLETE = "fedo_complete"


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
    # Asset management
    asset_ids: Dict[str, str] = field(default_factory=dict)  # role -> asset_id mapping
    primary_asset_id: Optional[str] = None  # Asset ID for display (must be image)


class ProgressCallback(Protocol):
    """Protocol for progress callback functions."""

    def __call__(self, event: EventType, progress: ProgressInfo) -> None: ...


# ============================================================================
# Base Processor Class
# ============================================================================

class BaseDatasetProcessor(ABC):
    """
    Abstract base class for dataset processors.

    Each dataset type (CLASSIC, FEDO, etc.) implements this interface
    to handle data upload and processing:

    1. File Upload & Processing:
       - validate_file() - Check if file can be processed
       - process_upload() - Process uploaded file, create sample data

    2. Asset Management:
       - Uploads files to object storage via AssetService
       - Returns asset_ids and primary_asset_id for Sample

    Example:
        @register_processor
        class FedoProcessor(BaseDatasetProcessor):
            system_type = DatasetType.FEDO

            async def process_upload(self, file, context, progress_callback):
                # Parse, calculate physics, generate visualizations
                return ProcessResult(
                    success=True,
                    asset_ids={"raw_text": "...", "time_energy_image": "..."},
                    primary_asset_id="...",
                )
    """

    # Class attribute: which dataset type this processor supports
    system_type: DatasetType

    def __init__(self, session: Optional["AsyncSession"] = None):
        self._event_listeners: Dict[EventType, List[Callable]] = {}
        self.logger = logger.bind(component=f"{__name__}.{self.__class__.__name__}")
        self.session = session
        self.asset_service: Optional["AssetService"] = None

        # Initialize asset service if session is provided
        if session:
            from saki_api.services.storage.asset import AssetService
            self.asset_service = AssetService(session)

    # ==================== Event System ====================

    def emit(self, event: EventType, data: Any = None) -> None:
        """Emit an event to all registered listeners."""
        if event in self._event_listeners:
            for callback in self._event_listeners[event]:
                try:
                    callback(event, data)
                except Exception as e:
                    self.logger.error("事件监听器执行失败 event={} error={}", event, e)

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
        """File extensions this processor can process (e.g., {'.jpg', '.png'})."""
        pass

    def validate_file(self, file_path: Path, context: UploadContext) -> tuple[bool, str]:
        """
        Validate if a file can be processed.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if file_path.suffix.lower() not in self.supported_extensions:
            return False, f"Unsupported file extension: {file_path.suffix}"

        # In-memory upload may not have a real file path
        if not file_path.exists():
            if context.config.get("in_memory", False):
                return True, ""
            return False, "File does not exist"

        return True, ""

    @abstractmethod
    async def process_upload(
            self,
            file: "UploadFile",
            context: UploadContext,
            progress_callback: Optional[ProgressCallback] = None,
    ) -> ProcessResult:
        """
        Process an uploaded file.

        Args:
            file: Uploaded file (UploadFile from FastAPI)
            context: Upload context with dataset info
            progress_callback: Optional progress callback

        Returns:
            ProcessResult with sample fields to save
        """
        pass

    # ==================== Utilities ====================

    def generate_id(self) -> str:
        """Generate a unique sample ID."""
        return str(uuid.uuid4())

    def create_progress(self, total: int, message: str = "") -> ProgressInfo:
        """Create a new ProgressInfo instance."""
        return ProgressInfo(total=total, message=message)

    def _update_progress(
            self,
            progress_callback: Optional[ProgressCallback],
            progress: Optional[ProgressInfo],
            current: int,
            message: str,
            stage: str,
    ) -> None:
        """Helper method to update progress if callback is provided."""
        if not progress_callback or not progress:
            return
        progress.update(current, message, stage)
        progress_callback(EventType.PROCESS_PROGRESS, progress)
