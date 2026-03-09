from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin


class RuntimeRelease(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_release"

    component_type: str = Field(index=True, max_length=16)
    component_name: str = Field(index=True, max_length=255)
    version: str = Field(max_length=64)
    asset_id: uuid.UUID = Field(foreign_key="asset.id", index=True)
    sha256: str = Field(max_length=64)
    size_bytes: int = Field(default=0)
    format: str = Field(default="tar.gz", max_length=32)
    manifest_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")
