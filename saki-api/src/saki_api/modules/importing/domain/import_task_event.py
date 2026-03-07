from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, UUIDMixin


class ImportTaskEvent(UUIDMixin, SQLModel, table=True):
    __tablename__ = "import_task_event"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_import_task_event_task_seq"),)

    task_id: uuid.UUID = Field(foreign_key="import_task.id", index=True)
    seq: int = Field(index=True, ge=1)
    ts: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        index=True,
        sa_type=sa.DateTime(timezone=True),
    )

    event_type: str = Field(max_length=32, index=True)
    event_subtype: str | None = Field(default=None, max_length=64)
    phase: str | None = Field(default=None, max_length=128)
    message: str | None = Field(default=None, max_length=2000)
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    item_key: str | None = Field(default=None, max_length=1024)
    status: str | None = Field(default=None, max_length=128)
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
