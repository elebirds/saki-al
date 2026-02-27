"""AL snapshot version model."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin
from saki_api.modules.shared.modeling.enums import SnapshotUpdateMode, SnapshotValPolicy


class ALSnapshotVersion(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "al_snapshot_version"
    __table_args__ = (UniqueConstraint("loop_id", "version_index", name="uq_al_snapshot_version_loop_version"),)

    loop_id: uuid.UUID = Field(foreign_key="loop.id", index=True)
    version_index: int = Field(default=1, ge=1, index=True)
    parent_version_id: uuid.UUID | None = Field(default=None, foreign_key="al_snapshot_version.id", index=True)

    update_mode: SnapshotUpdateMode = Field(default=SnapshotUpdateMode.INIT, index=True)
    val_policy: SnapshotValPolicy = Field(default=SnapshotValPolicy.ANCHOR_ONLY, index=True)
    seed: str = Field(default="", max_length=128)
    rule_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    manifest_hash: str = Field(default="", max_length=64, index=True)
    sample_count: int = Field(default=0, ge=0)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
