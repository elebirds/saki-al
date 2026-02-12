"""Candidate samples selected by runtime tasks."""

import uuid
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.models.base import OPT_JSON, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.runtime.job_task import JobTask


class TaskCandidateItem(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "task_candidate_item"
    __table_args__ = (UniqueConstraint("task_id", "sample_id", name="uq_task_candidate_item"),)

    task_id: uuid.UUID = Field(foreign_key="job_task.id", index=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True)
    rank: int = Field(default=0, ge=0)
    score: float = Field(default=0.0)
    reason: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    prediction_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    task: "JobTask" = Relationship(back_populates="candidates")
