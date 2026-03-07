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
    YOLO_OBB = "yolo_obb"
    DOTA = "dota"


class ConflictStrategy(str, Enum):
    REPLACE = "replace"
    MERGE = "merge"


class PathFlattenMode(str, Enum):
    BASENAME = "basename"
    PRESERVE_PATH = "preserve_path"


class NameCollisionPolicy(str, Enum):
    ABORT = "abort"
    AUTO_RENAME = "auto_rename"
    OVERWRITE = "overwrite"


class AssociatedDatasetMode(str, Enum):
    EXISTING = "existing"
    NEW = "new"


class ImportUploadStrategy(str, Enum):
    SINGLE_PUT = "single_put"
    MULTIPART = "multipart"


class ImportUploadSessionStatus(str, Enum):
    INITIATED = "initiated"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    ABORTED = "aborted"
    EXPIRED = "expired"
    CONSUMED = "consumed"


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


class ImportTaskResultResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ImportUploadInitRequest(BaseModel):
    mode: str
    resource_type: str
    resource_id: uuid.UUID
    filename: str
    size: int = Field(ge=1)
    content_type: str = "application/zip"
    file_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class ImportUploadInitResponse(BaseModel):
    session_id: uuid.UUID
    strategy: ImportUploadStrategy
    status: ImportUploadSessionStatus
    reuse_hit: bool = False
    object_key: str
    expires_at: datetime
    part_size: int
    upload_id: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class ImportUploadPartSignRequest(BaseModel):
    part_numbers: list[int] = Field(default_factory=list)


class ImportUploadPartSignedItem(BaseModel):
    part_number: int
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class ImportUploadPartSignResponse(BaseModel):
    session_id: uuid.UUID
    upload_id: str
    parts: list[ImportUploadPartSignedItem] = Field(default_factory=list)


class ImportUploadCompletedPart(BaseModel):
    part_number: int
    etag: str


class ImportUploadCompleteRequest(BaseModel):
    size: int = Field(ge=1)
    parts: list[ImportUploadCompletedPart] = Field(default_factory=list)


class ImportUploadSessionResponse(BaseModel):
    session_id: uuid.UUID
    mode: str
    resource_type: str
    resource_id: uuid.UUID
    filename: str
    size: int
    uploaded_size: int
    content_type: str
    object_key: str
    strategy: ImportUploadStrategy
    status: ImportUploadSessionStatus
    upload_id: str | None = None
    expires_at: datetime | None = None
    error: str | None = None


class ImportUploadAbortResponse(BaseModel):
    session_id: uuid.UUID
    status: ImportUploadSessionStatus


class DatasetImportPrepareRequest(BaseModel):
    upload_session_id: uuid.UUID
    path_flatten_mode: PathFlattenMode = PathFlattenMode.BASENAME
    name_collision_policy: NameCollisionPolicy = NameCollisionPolicy.ABORT


class ProjectAnnotationImportPrepareRequest(BaseModel):
    upload_session_id: uuid.UUID
    format_profile: ImportFormat
    dataset_id: uuid.UUID
    branch_name: str = "master"
    path_flatten_mode: PathFlattenMode = PathFlattenMode.BASENAME
    name_collision_policy: NameCollisionPolicy = NameCollisionPolicy.ABORT


class ProjectAssociatedImportPrepareRequest(BaseModel):
    upload_session_id: uuid.UUID
    format_profile: ImportFormat
    branch_name: str = "master"
    path_flatten_mode: PathFlattenMode = PathFlattenMode.BASENAME
    name_collision_policy: NameCollisionPolicy = NameCollisionPolicy.ABORT
    target_dataset_mode: AssociatedDatasetMode
    target_dataset_id: uuid.UUID | None = None
    new_dataset_name: str | None = None
    new_dataset_description: str | None = None


class ImportImageEntry(BaseModel):
    zip_entry_path: str
    resolved_sample_name: str
    original_relative_path: str
    collision_action: str = "none"


class SampleBulkImportRequest(BaseModel):
    preview_token: str | None = None
    zip_asset_id: uuid.UUID | None = None
    image_entries: list[ImportImageEntry] = Field(default_factory=list)


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
