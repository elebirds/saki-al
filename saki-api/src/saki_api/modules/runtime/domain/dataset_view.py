"""Round-level dataset manifest view models."""

from __future__ import annotations

import uuid

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin


class RoundDatasetView(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "round_dataset_view"

    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)
    round_id: uuid.UUID = Field(foreign_key="round.id", index=True)
    split: str = Field(max_length=32)
    is_static: bool = Field(default=False)
    snapshot_id: uuid.UUID = Field(foreign_key="dataset_snapshot.id", index=True)
    selector_encoding: str = Field(max_length=16)
    selector_bytes: bytes
    selector_cardinality: int = Field(ge=0)
    selector_checksum: str = Field(max_length=128)
    manifest_ref: str = Field(max_length=512)


class ALSessionState(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "al_session_state"

    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)
    round_id: uuid.UUID | None = Field(default=None, foreign_key="round.id")
    snapshot_id: uuid.UUID = Field(foreign_key="dataset_snapshot.id")
    selector_encoding: str = Field(max_length=16)
    selector_bytes: bytes
    selector_cardinality: int = Field(ge=0)
    selector_checksum: str = Field(max_length=128)
    selector_manifest_ref: str | None = Field(default=None, max_length=512)
    round_index: int = Field(default=0, ge=0)
