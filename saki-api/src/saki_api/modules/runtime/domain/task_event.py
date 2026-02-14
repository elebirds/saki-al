"""Persistent event stream for runtime tasks."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.job_task import JobTask


class TaskEvent(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "step_event"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_step_event_seq"),)

    task_id: uuid.UUID = Field(foreign_key="step.id", index=True)
    seq: int = Field(index=True, ge=1)
    ts: datetime = Field(index=True)
    event_type: str = Field(index=True, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    request_id: str | None = Field(default=None, max_length=128)

    task: "JobTask" = Relationship(back_populates="events")
