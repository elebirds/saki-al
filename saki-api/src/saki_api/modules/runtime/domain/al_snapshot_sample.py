"""AL snapshot sample membership model."""

from __future__ import annotations

import uuid

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.enums import SnapshotPartition


class ALSnapshotSample(SQLModel, table=True):
    __tablename__ = "al_snapshot_sample"

    snapshot_version_id: uuid.UUID = Field(primary_key=True, foreign_key="al_snapshot_version.id")
    sample_id: uuid.UUID = Field(primary_key=True, foreign_key="sample.id")
    partition: SnapshotPartition = Field(index=True)
    cohort_index: int = Field(default=0, ge=0, index=True)
    locked: bool = Field(default=False, index=True)
