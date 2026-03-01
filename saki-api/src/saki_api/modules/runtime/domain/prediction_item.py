"""Prediction item rows generated under a prediction set."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin


class PredictionItem(TimestampMixin, SQLModel, table=True):
    __tablename__ = "prediction_item"

    prediction_set_id: uuid.UUID = Field(primary_key=True, foreign_key="prediction_set.id")
    sample_id: uuid.UUID = Field(primary_key=True, foreign_key="sample.id")

    rank: int = Field(default=0, ge=0, index=True)
    score: float = Field(default=0.0)
    label_id: uuid.UUID | None = Field(default=None, foreign_key="label.id", index=True)
    geometry: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    attrs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
    confidence: float = Field(default=0.0)
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
