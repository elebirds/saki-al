from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin


class RuntimeUpdateAttempt(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_update_attempt"

    executor_id: str = Field(index=True, max_length=128)
    component_type: str = Field(max_length=16)
    component_name: str = Field(max_length=255)
    request_id: str = Field(index=True, unique=True, max_length=128)
    from_version: str = Field(max_length=64)
    target_version: str = Field(max_length=64)
    status: str = Field(index=True, max_length=32)
    detail: str | None = Field(default=None, max_length=4000)
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    rolled_back: bool = Field(default=False)
    rollback_detail: str | None = Field(default=None, max_length=4000)
