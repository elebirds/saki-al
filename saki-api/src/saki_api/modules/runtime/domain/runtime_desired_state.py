from __future__ import annotations

import uuid

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin


class RuntimeDesiredState(TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_desired_state"

    component_type: str = Field(primary_key=True, max_length=16)
    component_name: str = Field(primary_key=True, max_length=255)
    release_id: uuid.UUID = Field(foreign_key="runtime_release.id", index=True)
    updated_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")
