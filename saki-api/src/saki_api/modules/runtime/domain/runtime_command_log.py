"""Idempotent runtime command log."""

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin


class RuntimeCommandLog(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_command_log"

    command_id: str = Field(max_length=128, unique=True, index=True)
    command_type: str = Field(max_length=64, index=True)
    resource_id: str = Field(default="", max_length=128, index=True)
    status: str = Field(default="accepted", max_length=32, index=True)
    detail: str = Field(default="")
