"""Persistent event stream for runtime tasks."""

import uuid
from datetime import datetime
from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

class TaskEvent(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_event"
    __table_args__ = (UniqueConstraint("task_id", "execution_id", "seq", name="uq_task_event_execution_seq"),)

    task_id: uuid.UUID = Field(foreign_key="task.id", index=True)
    execution_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True)
    seq: int = Field(index=True, ge=1)
    ts: datetime = Field(index=True, sa_type=sa.DateTime(timezone=True))
    event_type: str = Field(index=True, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
