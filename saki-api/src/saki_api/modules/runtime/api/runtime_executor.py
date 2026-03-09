"""
Runtime executor observability schemas.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


RuntimeComponentType = Literal["executor", "plugin"]


class RuntimeUpdateAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    executor_id: str
    component_type: RuntimeComponentType
    component_name: str
    request_id: str
    from_version: str
    target_version: str
    status: str
    detail: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    rolled_back: bool = False
    rollback_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeUpdateAttemptListResponse(BaseModel):
    items: list[RuntimeUpdateAttemptRead] = Field(default_factory=list)


class RuntimeReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    component_type: RuntimeComponentType
    component_name: str
    version: str
    asset_id: uuid.UUID
    sha256: str
    size_bytes: int
    format: str
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeReleaseListResponse(BaseModel):
    items: list[RuntimeReleaseRead] = Field(default_factory=list)


class RuntimeDesiredStateItem(BaseModel):
    component_type: RuntimeComponentType
    component_name: str
    release: RuntimeReleaseRead


class RuntimeDesiredStateResponse(BaseModel):
    items: list[RuntimeDesiredStateItem] = Field(default_factory=list)


class RuntimeDesiredStatePatchItem(BaseModel):
    component_type: RuntimeComponentType
    component_name: str
    release_id: uuid.UUID | None = None


class RuntimeDesiredStatePatchRequest(BaseModel):
    items: list[RuntimeDesiredStatePatchItem] = Field(default_factory=list)


class RuntimeExecutorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    executor_id: str
    version: str
    status: str
    is_online: bool
    current_task_id: str | None = None
    plugin_ids: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    update_state: dict[str, Any] = Field(default_factory=dict)
    desired_executor_version: str | None = None
    desired_plugins: dict[str, str] = Field(default_factory=dict)
    drifted: bool = False
    drift_reasons: list[str] = Field(default_factory=list)
    last_seen_at: datetime | None = None
    last_error: str | None = None
    pending_assign_count: int = 0
    pending_stop_count: int = 0
    latest_update: RuntimeUpdateAttemptRead | None = None
    last_failed_update: RuntimeUpdateAttemptRead | None = None


class RuntimeExecutorSummary(BaseModel):
    total_count: int
    online_count: int
    busy_count: int
    available_count: int
    availability_rate: float
    pending_assign_count: int
    pending_stop_count: int
    drifted_count: int = 0
    updating_count: int = 0
    latest_heartbeat_at: datetime | None = None


class RuntimeExecutorListResponse(BaseModel):
    summary: RuntimeExecutorSummary
    items: list[RuntimeExecutorRead]


RuntimeExecutorStatsRange = Literal["30m", "1h", "6h", "24h", "7d"]


class RuntimeExecutorStatsPoint(BaseModel):
    ts: datetime
    total_count: int
    online_count: int
    busy_count: int
    available_count: int
    availability_rate: float
    pending_assign_count: int
    pending_stop_count: int


class RuntimeExecutorStatsResponse(BaseModel):
    range: RuntimeExecutorStatsRange
    bucket_seconds: int
    points: list[RuntimeExecutorStatsPoint] = Field(default_factory=list)


class RuntimePluginRead(BaseModel):
    plugin_id: str
    display_name: str
    version: str
    supported_task_types: list[str] = Field(default_factory=list)
    supported_strategies: list[str] = Field(default_factory=list)
    supported_accelerators: list[str] = Field(default_factory=list)
    supports_auto_fallback: bool = True
    request_config_schema: dict[str, Any] = Field(default_factory=dict)
    executors_total: int = 0
    executors_online: int = 0
    executors_available: int = 0
    availability_rate: float = 0.0
    has_conflict: bool = False
    conflict_fields: list[str] = Field(default_factory=list)


class RuntimePluginCatalogResponse(BaseModel):
    items: list[RuntimePluginRead] = Field(default_factory=list)


class RuntimeDomainStatusResponse(BaseModel):
    configured: bool
    enabled: bool
    state: str
    target: str = ""
    consecutive_failures: int = 0
    last_error: str = ""
    last_connected_at: datetime | None = None
    next_retry_at: datetime | None = None


class RuntimeDomainCommandResponse(BaseModel):
    command_id: str
    request_id: str
    status: str
    message: str
