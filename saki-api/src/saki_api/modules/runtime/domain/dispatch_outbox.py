"""Transactional outbox for reliable step dispatch delivery."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import Column, Index
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.step import Step


class DispatchOutbox(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "dispatch_outbox"
    __table_args__ = (
        Index("ix_dispatch_outbox_status_next_attempt_at", "status", "next_attempt_at"),
    )

    step_id: uuid.UUID = Field(foreign_key="step.id", index=True)
    executor_id: str = Field(max_length=128)
    request_id: str = Field(max_length=128, unique=True, index=True)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    status: str = Field(max_length=32)
    attempt_count: int = Field(ge=0)
    next_attempt_at: datetime = Field()
    locked_at: datetime | None = Field(default=None)
    sent_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=4000)

    step: "Step" = Relationship(back_populates="dispatch_outboxes")
