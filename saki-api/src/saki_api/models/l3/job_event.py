"""
Persistent event stream for jobs.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON

if TYPE_CHECKING:
    from saki_api.models.l3.job import Job


class JobEvent(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "job_event"
    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_job_event_seq"),
    )

    job_id: uuid.UUID = Field(foreign_key="job.id", index=True)
    seq: int = Field(index=True, ge=1)
    ts: datetime = Field(index=True)
    event_type: str = Field(index=True, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    request_id: str | None = Field(default=None, max_length=128)

    job: "Job" = Relationship(back_populates="events")
