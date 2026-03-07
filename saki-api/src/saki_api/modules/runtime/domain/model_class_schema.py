"""Model class-to-label schema bound at model publish time."""

from __future__ import annotations

import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin


class ModelClassSchema(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "model_class_schema"
    __table_args__ = (
        UniqueConstraint("model_id", "class_index", name="uq_model_class_schema_model_index"),
        UniqueConstraint("model_id", "class_name_norm", name="uq_model_class_schema_model_name_norm"),
    )

    model_id: uuid.UUID = Field(foreign_key="model.id", index=True)
    label_id: uuid.UUID = Field(foreign_key="label.id", index=True)
    class_index: int = Field(ge=0, index=True)
    class_name: str = Field(default="", max_length=255)
    class_name_norm: str = Field(default="", max_length=255)
    schema_hash: str = Field(default="", max_length=64, index=True)
