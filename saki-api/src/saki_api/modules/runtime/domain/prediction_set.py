"""Prediction model for assisted annotation feedback."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin


class Prediction(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "prediction"

    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    loop_id: uuid.UUID | None = Field(default=None, foreign_key="loop.id", index=True)
    plugin_id: str = Field(default="", max_length=255, index=True)
    source_round_id: uuid.UUID | None = Field(default=None, foreign_key="round.id", index=True)
    source_step_id: uuid.UUID | None = Field(default=None, foreign_key="step.id", index=True)
    model_id: uuid.UUID = Field(foreign_key="model.id", index=True)
    base_commit_id: uuid.UUID | None = Field(default=None, foreign_key="commit.id", index=True)
    task_id: uuid.UUID = Field(foreign_key="task.id", index=True, unique=True)

    scope_type: str = Field(default="snapshot_scope", max_length=64, index=True)
    scope_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    status: str = Field(default="pending", max_length=32, index=True)
    total_items: int = Field(default=0, ge=0)
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    last_error: str | None = Field(default=None, max_length=4000)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)


# Temporary alias for residual imports during hard cut.
PredictionSet = Prediction
