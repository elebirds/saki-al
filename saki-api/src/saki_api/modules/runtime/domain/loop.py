import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import LoopMode, LoopPhase, LoopLifecycle

if TYPE_CHECKING:
    from saki_api.modules.project.domain.branch import Branch
    from saki_api.modules.project.domain.project import Project
    from saki_api.modules.runtime.domain.round import Round


class Loop(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """L3 loop container for runtime orchestration."""

    __tablename__ = "loop"
    __table_args__ = (UniqueConstraint("branch_id", name="uq_loop_branch_id"),)

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    branch_id: uuid.UUID = Field(foreign_key="branch.id", index=True)

    name: str = Field(max_length=100)
    mode: LoopMode = Field(default=LoopMode.ACTIVE_LEARNING, index=True)
    phase: LoopPhase = Field(default=LoopPhase.AL_BOOTSTRAP, index=True)
    phase_meta: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    model_arch: str

    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    current_iteration: int = Field(default=0)
    lifecycle: LoopLifecycle = Field(default=LoopLifecycle.DRAFT, index=True)
    max_rounds: int = Field(default=5, ge=1)
    query_batch_size: int = Field(default=200, ge=1)
    min_seed_labeled: int = Field(default=100, ge=1)
    min_new_labels_per_round: int = Field(default=120, ge=1)
    stop_patience_rounds: int = Field(default=2, ge=1)
    stop_min_gain: float = Field(default=0.002)
    auto_register_model: bool = Field(default=True)

    active_snapshot_version_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="loop_snapshot_version.id",
        index=True,
    )
    last_confirmed_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id", index=True)
    terminal_reason: str | None = Field(default=None, max_length=4000)

    project: "Project" = Relationship(back_populates="loops")
    branch: "Branch" = Relationship(back_populates="loop")
    rounds: List["Round"] = Relationship(
        back_populates="loop",
        sa_relationship_kwargs={"foreign_keys": "[Round.loop_id]"},
    )
