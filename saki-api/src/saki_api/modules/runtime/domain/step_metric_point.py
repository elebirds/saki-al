"""Time-series metric points for runtime steps."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Integer
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.step import Step


class StepMetricPoint(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "step_metric_point"

    step_id: uuid.UUID = Field(foreign_key="step.id", index=True)
    metric_step: int = Field(default=0, ge=0, sa_column=Column("step", Integer, nullable=False, index=True))
    epoch: Optional[int] = Field(default=None, index=True)
    metric_name: str = Field(index=True, max_length=128)
    metric_value: float
    ts: datetime = Field(index=True)

    step: "Step" = Relationship(
        back_populates="metric_points",
        sa_relationship_kwargs={"foreign_keys": "[StepMetricPoint.step_id]"},
    )

    # Backward compatibility.
    @property
    def task_id(self) -> uuid.UUID:
        return self.step_id

    @task_id.setter
    def task_id(self, value: uuid.UUID) -> None:
        self.step_id = value
