"""Transactional outbox for reliable task dispatch delivery."""

import uuid
from datetime import datetime
from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import Column, Index
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

class DispatchOutbox(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "dispatch_outbox"
    __table_args__ = (
        Index("ix_dispatch_outbox_status_next_attempt_at", "status", "next_attempt_at"),
    )

    task_id: uuid.UUID = Field(foreign_key="task.id", index=True)
    executor_id: str = Field(max_length=128)
    request_id: str = Field(max_length=128, unique=True, index=True)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    status: str = Field(max_length=32)
    attempt_count: int = Field(ge=0)
    next_attempt_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    locked_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    sent_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    last_error: str | None = Field(default=None, max_length=4000)
