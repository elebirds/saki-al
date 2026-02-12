"""DTOs for runtime dispatch application layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskDispatchPayloadDTO(BaseModel):
    task_id: str
    job_id: str
    loop_id: str
    project_id: str
    source_commit_id: str
    task_type: str
    plugin_id: str
    mode: str
    query_strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    round_index: int = Field(default=0)
    attempt: int = Field(default=1)
    depends_on_task_ids: list[str] = Field(default_factory=list)

