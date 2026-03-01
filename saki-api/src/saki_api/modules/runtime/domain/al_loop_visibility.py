"""AL loop visibility model."""

from __future__ import annotations

import uuid

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin
from saki_api.modules.shared.modeling.enums import VisibilitySource


class ALLoopVisibility(TimestampMixin, SQLModel, table=True):
    __tablename__ = "loop_sample_state"

    loop_id: uuid.UUID = Field(primary_key=True, foreign_key="loop.id")
    sample_id: uuid.UUID = Field(primary_key=True, foreign_key="sample.id")
    visible_in_train: bool = Field(default=False, index=True)
    source: VisibilitySource = Field(default=VisibilitySource.SNAPSHOT_INIT, index=True)
    revealed_round_index: int | None = Field(default=None, ge=0, index=True)
    reveal_commit_id: uuid.UUID | None = Field(default=None, foreign_key="commit.id", index=True)
