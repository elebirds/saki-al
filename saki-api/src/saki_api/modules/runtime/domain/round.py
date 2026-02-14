"""Round model for loop-level aggregation."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import LoopMode, RoundStatus

if TYPE_CHECKING:
    from saki_api.modules.project.domain.project import Project
    from saki_api.modules.runtime.domain.loop import Loop
    from saki_api.modules.runtime.domain.model import Model
    from saki_api.modules.runtime.domain.step import Step


class RoundBase(SQLModel):
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)

    round_index: int = Field(index=True)
    mode: LoopMode = Field(default=LoopMode.ACTIVE_LEARNING)

    state: RoundStatus = Field(default=RoundStatus.PENDING, index=True)
    step_counts: Dict[str, int] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    round_type: str = Field(default="loop_round", index=True)
    plugin_id: str = Field(default="", index=True)
    query_strategy: str = Field(default="random")
    resolved_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    input_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")
    output_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")

    assigned_executor_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    retry_count: int = Field(default=0)
    terminal_reason: Optional[str] = Field(default=None, max_length=4000)

    final_metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    final_artifacts: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    strategy_params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    model_id: Optional[uuid.UUID] = Field(default=None, foreign_key="model.id", index=True)


class Round(RoundBase, TimestampMixin, UUIDMixin, table=True):
    __tablename__ = "round"
    __table_args__ = (UniqueConstraint("loop_id", "round_index", name="uq_round_loop_round"),)

    project: "Project" = Relationship(back_populates="jobs")
    loop: "Loop" = Relationship(
        back_populates="rounds",
        sa_relationship_kwargs={"foreign_keys": "[Round.loop_id]"},
    )
    model: Optional["Model"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Round.model_id]"})
    steps: List["Step"] = Relationship(back_populates="round")

    # Backward compatibility properties.
    @property
    def summary_status(self) -> RoundStatus:
        return self.state

    @summary_status.setter
    def summary_status(self, value: RoundStatus) -> None:
        self.state = value

    @property
    def task_counts(self) -> Dict[str, int]:
        return self.step_counts

    @task_counts.setter
    def task_counts(self, value: Dict[str, int]) -> None:
        self.step_counts = value

    @property
    def job_type(self) -> str:
        return self.round_type

    @job_type.setter
    def job_type(self, value: str) -> None:
        self.round_type = value

    @property
    def params(self) -> Dict[str, Any]:
        return self.resolved_params

    @params.setter
    def params(self, value: Dict[str, Any]) -> None:
        self.resolved_params = value

    @property
    def source_commit_id(self) -> Optional[uuid.UUID]:
        return self.input_commit_id

    @source_commit_id.setter
    def source_commit_id(self, value: Optional[uuid.UUID]) -> None:
        self.input_commit_id = value

    @property
    def result_commit_id(self) -> Optional[uuid.UUID]:
        return self.output_commit_id

    @result_commit_id.setter
    def result_commit_id(self, value: Optional[uuid.UUID]) -> None:
        self.output_commit_id = value

    @property
    def last_error(self) -> Optional[str]:
        return self.terminal_reason

    @last_error.setter
    def last_error(self, value: Optional[str]) -> None:
        self.terminal_reason = value

    @property
    def tasks(self) -> List["Step"]:
        return self.steps

    @tasks.setter
    def tasks(self, value: List["Step"]) -> None:
        self.steps = value
