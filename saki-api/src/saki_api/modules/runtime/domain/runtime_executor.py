"""
Runtime executor online registry.
"""
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import UUIDMixin, TimestampMixin, OPT_JSON


class RuntimeExecutor(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "runtime_executor"

    executor_id: str = Field(index=True, unique=True, max_length=128)
    version: str = Field(default="", max_length=64)
    status: str = Field(default="offline", index=True, max_length=32)

    is_online: bool = Field(default=False, index=True)
    current_step_id: str | None = Field(default=None, index=True, max_length=64)

    plugin_ids: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    resources: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))

    last_seen_at: datetime | None = Field(default=None, index=True)
    last_error: str | None = Field(default=None, max_length=4000)

    # Backward compatibility.
    @property
    def current_task_id(self) -> str | None:
        return self.current_step_id

    @current_task_id.setter
    def current_task_id(self, value: str | None) -> None:
        self.current_step_id = value
