"""Time-series metric points for runtime tasks."""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column, Integer
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin

class TaskMetricPoint(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_metric_point"

    task_id: uuid.UUID = Field(foreign_key="task.id", index=True)
    metric_step: int = Field(default=0, ge=0, sa_column=Column("step", Integer, nullable=False, index=True))
    epoch: Optional[int] = Field(default=None, index=True)
    metric_name: str = Field(index=True, max_length=128)
    metric_value: float
    ts: datetime = Field(index=True, sa_type=sa.DateTime(timezone=True))
