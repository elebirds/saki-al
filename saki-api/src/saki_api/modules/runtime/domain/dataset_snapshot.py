"""Dataset snapshot models for immutable UUID->ordinal mapping."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel


class DatasetSnapshot(SQLModel, table=True):
    __tablename__ = "dataset_snapshot"

    id: uuid.UUID = Field(primary_key=True)
    dataset_id: uuid.UUID = Field(foreign_key="dataset.id", index=True)
    parent_snapshot_id: uuid.UUID | None = Field(default=None, foreign_key="dataset_snapshot.id", index=True)
    universe_size: int = Field(ge=0)
    max_ordinal: int = Field(ge=0)
    created_at: datetime


class DatasetSnapshotSampleOrdinal(SQLModel, table=True):
    __tablename__ = "dataset_snapshot_sample_ordinal"

    snapshot_id: uuid.UUID = Field(foreign_key="dataset_snapshot.id", primary_key=True)
    sample_uuid: uuid.UUID = Field(primary_key=True)
    ordinal: int = Field(ge=0)
    is_tombstone: bool = Field(default=False)
    tombstone_at: datetime | None = Field(default=None)
    tombstone_reason: str | None = Field(default=None, max_length=255)
    created_at: datetime
    updated_at: datetime
