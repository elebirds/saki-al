"""Candidate samples selected by runtime tasks."""

import uuid
from typing import Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

class TaskCandidateItem(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_candidate_item"
    __table_args__ = (UniqueConstraint("task_id", "sample_id", name="uq_task_candidate_item"),)

    task_id: uuid.UUID = Field(foreign_key="task.id", index=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True)
    rank: int = Field(default=0, ge=0)
    score: float = Field(default=0.0)
    reason: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    prediction_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
