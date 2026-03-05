"""Frozen class mapping snapshot for prediction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin


class PredictionBinding(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "prediction_binding"

    prediction_set_id: uuid.UUID = Field(foreign_key="prediction.id", index=True, unique=True)
    model_id: uuid.UUID = Field(foreign_key="model.id", index=True)
    schema_hash: str = Field(default="", max_length=64, index=True)
    by_index_json: list[str] = Field(default_factory=list, sa_column=Column(OPT_JSON))
    by_name_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))


# Temporary alias for residual imports during hard cut.
PredictionSetBinding = PredictionBinding
