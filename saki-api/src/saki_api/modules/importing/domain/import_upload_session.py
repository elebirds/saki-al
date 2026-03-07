from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import OPT_JSON, TimestampMixin, UUIDMixin


class ImportUploadStrategy(str, Enum):
    SINGLE_PUT = "single_put"
    MULTIPART = "multipart"


class ImportUploadSessionStatus(str, Enum):
    INITIATED = "initiated"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    ABORTED = "aborted"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ImportUploadSession(UUIDMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "import_upload_session"

    user_id: uuid.UUID = Field(index=True)
    mode: str = Field(max_length=64, index=True)
    resource_type: str = Field(max_length=32, index=True)
    resource_id: uuid.UUID = Field(index=True)

    filename: str = Field(max_length=255)
    size: int = Field(ge=0)
    content_type: str = Field(max_length=127)
    file_sha256: str | None = Field(default=None, max_length=64)

    object_key: str = Field(max_length=1024)
    bucket: str | None = Field(default=None, max_length=255)
    strategy: str = Field(default=ImportUploadStrategy.SINGLE_PUT.value, max_length=32)
    multipart_upload_id: str | None = Field(default=None, max_length=256)

    status: str = Field(default=ImportUploadSessionStatus.INITIATED.value, max_length=32, index=True)
    error: str | None = Field(default=None, max_length=2000)

    uploaded_size: int = Field(default=0, ge=0)
    expires_at: datetime | None = Field(default=None, index=True, sa_type=sa.DateTime(timezone=True))
    completed_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))

    meta_info: dict[str, Any] = Field(default_factory=dict, sa_column=Column(OPT_JSON))
