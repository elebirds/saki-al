from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

YoloLabelFormat = Literal["det", "obb_rbox", "obb_poly8"]
FormatProfileId = Literal["coco", "voc", "yolo", "yolo_obb", "dota", "predictions_json"]
PredictionsJSONEntryTraceField = Literal["sample_id", "dataset_id", "annotation_commit_id", "branch_name", "exported_at"]
PredictionsJSONDetectionTraceField = Literal["annotation_id", "label_id", "source", "attrs"]
PredictionsJSONRectCompatField = Literal["xyxy", "xywh"]
PredictionsJSONObbCompatField = Literal["xyxyxyxy", "xywhr"]
PredictionsJSONFilterGroupOp = Literal["and", "or"]
PredictionsJSONFilterOperator = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "not_exists"]


class FormatProfileRead(BaseModel):
    id: FormatProfileId
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


class PredictionsJSONFilterRule(BaseModel):
    field: str
    operator: PredictionsJSONFilterOperator
    value: Any | None = None


class PredictionsJSONFilterGroup(BaseModel):
    op: PredictionsJSONFilterGroupOp
    items: list["PredictionsJSONFilterNode"] = Field(default_factory=list)


PredictionsJSONFilterNode = PredictionsJSONFilterGroup | PredictionsJSONFilterRule


class PredictionsJSONGeometryCompatFields(BaseModel):
    rect: list[PredictionsJSONRectCompatField] = Field(default_factory=list)
    obb: list[PredictionsJSONObbCompatField] = Field(default_factory=list)


class PredictionsJSONOptions(BaseModel):
    include_empty_entries: bool = False
    include_entry_trace_fields: list[PredictionsJSONEntryTraceField] = Field(default_factory=list)
    include_detection_trace_fields: list[PredictionsJSONDetectionTraceField] = Field(default_factory=list)
    geometry_compat_fields: PredictionsJSONGeometryCompatFields = Field(
        default_factory=lambda: PredictionsJSONGeometryCompatFields(
            rect=["xyxy", "xywh"],
            obb=["xyxyxyxy", "xywhr"],
        )
    )
    filter: PredictionsJSONFilterNode | None = None


class ProjectExportResolveRequest(BaseModel):
    dataset_ids: list[uuid.UUID] = Field(default_factory=list)
    snapshot: ExportSnapshot = Field(discriminator="type")
    sample_scope: Literal["all", "labeled", "unlabeled"] = "all"
    format_profile: FormatProfileId
    yolo_label_format: YoloLabelFormat | None = None
    predictions_json_options: PredictionsJSONOptions | None = None
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
    format_profile: FormatProfileId
    yolo_label_format: YoloLabelFormat | None = None
    predictions_json_options: PredictionsJSONOptions | None = None
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


PredictionsJSONFilterGroup.model_rebuild()
PredictionsJSONOptions.model_rebuild()
