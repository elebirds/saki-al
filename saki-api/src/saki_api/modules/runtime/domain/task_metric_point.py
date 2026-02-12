"""Time-series metric points for runtime tasks."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.job_task import JobTask


class TaskMetricPoint(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_metric_point"

    task_id: uuid.UUID = Field(foreign_key="job_task.id", index=True)
    step: int = Field(index=True, ge=0)
    epoch: Optional[int] = Field(default=None, index=True)
    metric_name: str = Field(index=True, max_length=128)
    metric_value: float
    ts: datetime = Field(index=True)

    task: "JobTask" = Relationship(back_populates="metric_points")
