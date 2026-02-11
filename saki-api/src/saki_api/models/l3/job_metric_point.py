"""
Time-series metric points for chart rendering.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from saki_api.models.l3.job import Job


class JobMetricPoint(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "job_metric_point"
    __table_args__ = (
        UniqueConstraint("job_id", "metric_name", "step", name="uq_job_metric_step"),
    )

    job_id: uuid.UUID = Field(foreign_key="job.id", index=True)
    step: int = Field(index=True, ge=0)
    epoch: int | None = Field(default=None, index=True)
    metric_name: str = Field(index=True, max_length=128)
    metric_value: float
    ts: datetime = Field(index=True)

    job: "Job" = Relationship(back_populates="metric_points")
