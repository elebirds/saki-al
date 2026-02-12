"""
System setting model.

Stores system-level runtime configuration values in key-value form.
"""

import uuid
from typing import Any, Dict

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin


class SystemSetting(SQLModel, TimestampMixin, table=True):
    """Database model for dynamic system settings."""

    __tablename__ = "system_setting"

    key: str = Field(primary_key=True, max_length=128, description="Unique setting key.")
    value_json: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="JSON payload storing the setting value.",
    )
    updated_by: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="Last updater user id.",
    )
