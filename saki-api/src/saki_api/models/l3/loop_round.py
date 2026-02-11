import uuid
from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON
from saki_api.models.enums import LoopRoundStatus

if TYPE_CHECKING:
    from saki_api.models.l3.loop import ALLoop
    from saki_api.models.l3.job import Job
    from saki_api.models.l3.annotation_batch import AnnotationBatch


class LoopRound(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "loop_round"

    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)
    round_index: int = Field(index=True, ge=1)
    source_commit_id: uuid.UUID = Field(foreign_key="commit.id", index=True)
    job_id: Optional[uuid.UUID] = Field(default=None, foreign_key="job.id", index=True)
    annotation_batch_id: Optional[uuid.UUID] = Field(default=None, foreign_key="annotation_batch.id", index=True)
    status: LoopRoundStatus = Field(default=LoopRoundStatus.TRAINING, index=True)
    metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    selected_count: int = Field(default=0, ge=0)
    labeled_count: int = Field(default=0, ge=0)
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)

    loop: "ALLoop" = Relationship(back_populates="rounds")
    job: Optional["Job"] = Relationship(
        back_populates="rounds",
        sa_relationship_kwargs={"foreign_keys": "[LoopRound.job_id]"},
    )
    annotation_batch: Optional["AnnotationBatch"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[LoopRound.annotation_batch_id]"}
    )
