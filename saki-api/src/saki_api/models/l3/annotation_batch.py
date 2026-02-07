import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import UUIDMixin, TimestampMixin, OPT_JSON
from saki_api.models.enums import AnnotationBatchStatus

if TYPE_CHECKING:
    from saki_api.models.l3.loop import ALLoop


class AnnotationBatch(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "annotation_batch"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)
    job_id: uuid.UUID = Field(foreign_key="job.id", index=True)
    round_index: int = Field(index=True, ge=1)
    status: AnnotationBatchStatus = Field(default=AnnotationBatchStatus.OPEN, index=True)
    total_count: int = Field(default=0, ge=0)
    annotated_count: int = Field(default=0, ge=0)
    closed_at: datetime | None = Field(default=None)
    meta: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    loop: "ALLoop" = Relationship(back_populates="annotation_batches")
    items: List["AnnotationBatchItem"] = Relationship(back_populates="batch", cascade_delete=True)


class AnnotationBatchItem(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "annotation_batch_item"

    batch_id: uuid.UUID = Field(foreign_key="annotation_batch.id", index=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True)
    rank: int = Field(ge=1, index=True)
    score: float = Field(index=True)
    reason: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    prediction_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    is_annotated: bool = Field(default=False, index=True)
    annotated_at: Optional[datetime] = Field(default=None)
    annotation_commit_id: Optional[uuid.UUID] = Field(default=None, foreign_key="commit.id")

    batch: "AnnotationBatch" = Relationship(back_populates="items")
