from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

YoloLabelFormat = Literal["det", "obb_rbox", "obb_poly8"]


class FormatProfileRead(BaseModel):
    id: Literal["coco", "voc", "yolo", "yolo_obb", "dota"]
    family: str
    supports_import: bool
    supports_export: bool
    supported_annotation_types: list[str] = Field(default_factory=list)
    yolo_label_options: list[str] = Field(default_factory=list)
    available: bool
    reason: str | None = None


class ProjectIOCapabilitiesRead(BaseModel):
    enabled_annotation_types: list[str] = Field(default_factory=list)
    export_profiles: list[FormatProfileRead] = Field(default_factory=list)
    import_profiles: list[FormatProfileRead] = Field(default_factory=list)


class ExportSnapshotBranchHead(BaseModel):
    type: Literal["branch_head"] = "branch_head"
    branch_name: str = "master"


class ExportSnapshotCommit(BaseModel):
    type: Literal["commit"] = "commit"
    commit_id: uuid.UUID


ExportSnapshot = ExportSnapshotBranchHead | ExportSnapshotCommit


class ProjectExportResolveRequest(BaseModel):
    dataset_ids: list[uuid.UUID] = Field(default_factory=list)
    snapshot: ExportSnapshot = Field(discriminator="type")
    sample_scope: Literal["all", "labeled", "unlabeled"] = "all"
    format_profile: Literal["coco", "voc", "yolo", "yolo_obb", "dota"]
    yolo_label_format: YoloLabelFormat | None = None
    include_assets: bool = True
    bundle_layout: Literal["merged_zip", "per_dataset_zip"] = "merged_zip"


class ProjectExportDatasetStat(BaseModel):
    dataset_id: uuid.UUID
    sample_count: int
    estimated_asset_bytes: int


class ProjectExportResolveResponse(BaseModel):
    resolved_commit_id: uuid.UUID
    dataset_stats: list[ProjectExportDatasetStat] = Field(default_factory=list)
    estimated_total_asset_bytes: int = 0
    format_compatibility: Literal["ok", "incompatible"] = "ok"
    blocked: bool = False
    block_reason: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    annotation_type_counts: dict[str, int] = Field(default_factory=dict)


class ProjectExportAssetRead(BaseModel):
    role: str
    asset_id: uuid.UUID
    filename: str | None = None
    size: int | None = None
    meta_info: dict = Field(default_factory=dict)
    download_url: str


class ProjectExportChunkRequest(BaseModel):
    resolved_commit_id: uuid.UUID
    dataset_ids: list[uuid.UUID] = Field(default_factory=list)
    sample_scope: Literal["all", "labeled", "unlabeled"] = "all"
    format_profile: Literal["coco", "voc", "yolo", "yolo_obb", "dota"]
    yolo_label_format: YoloLabelFormat | None = None
    bundle_layout: Literal["merged_zip", "per_dataset_zip"] = "merged_zip"
    include_assets: bool = True
    cursor: int | None = None
    limit: int = Field(default=200, ge=1, le=200)


class ProjectExportChunkFileRead(BaseModel):
    dataset_id: uuid.UUID
    sample_id: uuid.UUID | None = None
    path: str
    source_type: Literal["text", "url"]
    text_content: str | None = None
    download_url: str | None = None
    size: int | None = None
    role: str | None = None


class ProjectExportChunkResponse(BaseModel):
    next_cursor: int | None = None
    sample_count: int = 0
    files: list[ProjectExportChunkFileRead] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
