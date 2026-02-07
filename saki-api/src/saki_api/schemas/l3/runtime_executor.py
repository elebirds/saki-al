"""
Runtime executor observability schemas.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class RuntimeExecutorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    executor_id: str
    version: str
    status: str
    is_online: bool
    current_job_id: str | None = None
    plugin_ids: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime | None = None
    last_error: str | None = None
    pending_assign_count: int = 0
    pending_stop_count: int = 0


class RuntimeExecutorSummary(BaseModel):
    online_count: int
    busy_count: int
    pending_assign_count: int
    pending_stop_count: int
    latest_heartbeat_at: datetime | None = None


class RuntimeExecutorListResponse(BaseModel):
    summary: RuntimeExecutorSummary
    items: list[RuntimeExecutorRead]
