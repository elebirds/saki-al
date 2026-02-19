from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ImportFormat(str, Enum):
    COCO = "coco"
    VOC = "voc"
    YOLO = "yolo"


class ConflictStrategy(str, Enum):
    REPLACE = "replace"
    MERGE = "merge"


class AssociatedDatasetMode(str, Enum):
    EXISTING = "existing"
    NEW = "new"


class ImportProgressEventType(str, Enum):
    START = "start"
    PHASE = "phase"
    ITEM = "item"
    ANNOTATION = "annotation"
    WARNING = "warning"
    ERROR = "error"
    COMPLETE = "complete"


class ImportIssue(BaseModel):
    code: str
    message: str
    path: str | None = None
    detail: dict[str, Any] | None = None


class ImportDryRunResponse(BaseModel):
    preview_token: str
    expires_at: datetime
    summary: dict[str, Any] = Field(default_factory=dict)
    planned_new_labels: list[str] = Field(default_factory=list)
    warnings: list[ImportIssue] = Field(default_factory=list)
    errors: list[ImportIssue] = Field(default_factory=list)


class ImportExecuteRequest(BaseModel):
    preview_token: str
    conflict_strategy: ConflictStrategy = ConflictStrategy.REPLACE
    confirm_create_labels: bool = False


class ImportProgressEvent(BaseModel):
    seq: int | None = None
    ts: datetime | None = None
    event: ImportProgressEventType
    event_subtype: str | None = None
    phase: str | None = None
    message: str | None = None
    current: int | None = None
    total: int | None = None
    item_key: str | None = None
    status: str | None = None
    detail: dict[str, Any] | None = None


class AnnotationDryRunPayload(BaseModel):
    format: ImportFormat
    dataset_id: uuid.UUID
    branch_name: str = "master"


class AssociatedDryRunPayload(BaseModel):
    format: ImportFormat
    branch_name: str = "master"
    target_dataset_mode: AssociatedDatasetMode
    target_dataset_id: uuid.UUID | None = None
    new_dataset_name: str | None = None
    new_dataset_description: str | None = None


class AssociatedManifestTarget(BaseModel):
    mode: AssociatedDatasetMode
    dataset_id: uuid.UUID | None = None
    new_dataset_name: str | None = None
    new_dataset_description: str | None = None


class ImportTaskCreateResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    stream_url: str
    status_url: str


class ImportTaskStatusResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    progress: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SampleBulkImportRequest(BaseModel):
    preview_token: str | None = None
    zip_asset_id: uuid.UUID | None = None
    image_paths: list[str] = Field(default_factory=list)


class AnnotationBulkSource(str, Enum):
    DIRECT = "direct"
    IMPORT_PREVIEW = "import_preview"


class AnnotationBulkRequest(BaseModel):
    source: AnnotationBulkSource = AnnotationBulkSource.DIRECT
    branch_name: str = "master"
    commit_message: str = "Bulk annotation save"
    conflict_strategy: ConflictStrategy = ConflictStrategy.REPLACE
    confirm_create_labels: bool = False
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    preview_token: str | None = None
