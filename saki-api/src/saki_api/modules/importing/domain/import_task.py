from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin


class ImportTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


class ImportTask(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "import_task"

    mode: str = Field(max_length=64, index=True)
    resource_type: str = Field(max_length=32, index=True)
    resource_id: uuid.UUID = Field(index=True)
    user_id: uuid.UUID = Field(index=True)

    status: str = Field(default=ImportTaskStatus.QUEUED.value, index=True, max_length=32)
    progress_current: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    phase: str | None = Field(default=None, max_length=128)

    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    error: str | None = Field(default=None, max_length=2000)

    started_at: datetime | None = Field(default=None, index=True)
    finished_at: datetime | None = Field(default=None, index=True)
