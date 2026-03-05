"""Persistent event stream for runtime tasks."""

import uuid
from datetime import datetime
from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import Column, UniqueConstraint
from pydantic import model_validator
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

class TaskEvent(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_event"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_event_seq"),)

    task_id: uuid.UUID = Field(foreign_key="task.id", index=True)
    seq: int = Field(index=True, ge=1)
    ts: datetime = Field(index=True, sa_type=sa.DateTime(timezone=True))
    event_type: str = Field(index=True, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    @model_validator(mode="before")
    @classmethod
    def _compat_step_id(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("task_id") is None and data.get("step_id") is not None:
            patched = dict(data)
            patched["task_id"] = patched.get("step_id")
            return patched
        return data

# Legacy alias, kept for incremental refactor of imports.
StepEvent = TaskEvent
