"""Candidate samples selected by runtime steps."""

import uuid
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.runtime.domain.step import Step


class StepCandidateItem(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "step_candidate_item"
    __table_args__ = (UniqueConstraint("step_id", "sample_id", name="uq_step_candidate_item"),)

    step_id: uuid.UUID = Field(foreign_key="step.id", index=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True)
    rank: int = Field(default=0, ge=0)
    score: float = Field(default=0.0)
    reason: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    prediction_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    step: "Step" = Relationship(back_populates="candidates")
