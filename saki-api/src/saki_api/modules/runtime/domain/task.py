"""Task model for unified runtime execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import RuntimeTaskKind, RuntimeTaskStatus, RuntimeTaskType


class Task(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    kind: RuntimeTaskKind = Field(default=RuntimeTaskKind.STEP, index=True)
    task_type: RuntimeTaskType = Field(default=RuntimeTaskType.CUSTOM, index=True)
    status: RuntimeTaskStatus = Field(default=RuntimeTaskStatus.PENDING, index=True)

    plugin_id: str = Field(default="", max_length=255, index=True)
    depends_on_task_ids: list[str] = Field(default_factory=list, sa_column=Column(OPT_JSON))
    input_commit_id: uuid.UUID | None = Field(default=None, foreign_key="commit.id", index=True)
    resolved_params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    assigned_executor_id: str | None = Field(default=None, index=True)

    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    started_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    ended_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    last_error: str | None = Field(default=None, max_length=4000)
