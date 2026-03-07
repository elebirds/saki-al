"""Manual override records for AL round candidate selection."""

from __future__ import annotations

import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import RoundSelectionOverrideOp


class ALRoundSelectionOverride(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "round_selection_override"
    __table_args__ = (
        UniqueConstraint("round_id", "sample_id", name="uq_round_selection_override_round_sample"),
    )

    round_id: uuid.UUID = Field(foreign_key="round.id", index=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True)
    op: RoundSelectionOverrideOp = Field(index=True)
    created_by: uuid.UUID | None = Field(default=None, index=True)
    reason: str | None = Field(default=None, max_length=4000)
