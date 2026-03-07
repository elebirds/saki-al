"""Round model for loop-level aggregation."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import LoopMode, RoundStatus

if TYPE_CHECKING:
    from saki_api.modules.project.domain.project import Project
    from saki_api.modules.runtime.domain.loop import Loop
    from saki_api.modules.runtime.domain.step import Step


class RoundBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    round_index: int = Field(index=True)
    attempt_index: int = Field(default=1, ge=1, index=True)
    mode: LoopMode = Field(default=LoopMode.ACTIVE_LEARNING)

    state: RoundStatus = Field(default=RoundStatus.PENDING, index=True)
    step_counts: Dict[str, int] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    plugin_id: str = Field(default="", index=True)
    resolved_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    input_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")
    retry_of_round_id: Optional[uuid.UUID] = Field(default=None, foreign_key="round.id")
    retry_reason: Optional[str] = Field(default=None, max_length=4000)

    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None, sa_type=sa.DateTime(timezone=True))
    ended_at: Optional[datetime] = Field(default=None, sa_type=sa.DateTime(timezone=True))
    terminal_reason: Optional[str] = Field(default=None, max_length=4000)
    confirmed_at: Optional[datetime] = Field(default=None, sa_type=sa.DateTime(timezone=True), index=True)
    confirmed_revealed_count: int = Field(default=0, ge=0)
    confirmed_selected_count: int = Field(default=0, ge=0)
    confirmed_effective_min_required: int = Field(default=0, ge=0)

    final_metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    final_artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))


class Round(RoundBase, TimestampMixin, UUIDMixin, table=True):
    __tablename__ = "round"
    __table_args__ = (
        UniqueConstraint("loop_id", "round_index", "attempt_index", name="uq_round_loop_round_attempt"),
    )

    project: "Project" = Relationship(back_populates="rounds")
    loop: "Loop" = Relationship(
        back_populates="rounds",
        sa_relationship_kwargs={"foreign_keys": "[Round.loop_id]"},
    )
    steps: List["Step"] = Relationship(back_populates="round")
