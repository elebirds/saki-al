"""
Runtime executor aggregated stats time-series snapshots.
"""

from datetime import datetime

from sqlmodel import SQLModel, Field

from saki_api.models.base import UUIDMixin, TimestampMixin


class RuntimeExecutorStats(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_executor_stats"

    ts: datetime = Field(index=True)
    total_count: int = Field(default=0, ge=0)
    online_count: int = Field(default=0, ge=0)
    busy_count: int = Field(default=0, ge=0)
    available_count: int = Field(default=0, ge=0)
    availability_rate: float = Field(default=0.0, ge=0.0)
    pending_assign_count: int = Field(default=0, ge=0)
    pending_stop_count: int = Field(default=0, ge=0)
