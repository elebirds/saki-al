"""DTOs for runtime control-plane ingress messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeDataRequestDTO:
    request_id: str
    task_id: str
    query_type: int
    project_id: uuid.UUID
    commit_id: uuid.UUID
    limit: int
    offset: int


@dataclass(slots=True)
class RuntimeUploadTicketRequestDTO:
    request_id: str
    task_id: str
    artifact_name: str
    content_type: str


@dataclass(slots=True)
class RuntimePluginCapabilityDTO:
    plugin_id: str
    version: str = ""
    supported_task_types: list[str] = field(default_factory=list)
    supported_strategies: list[str] = field(default_factory=list)
    display_name: str = ""
    request_config_schema: dict[str, Any] = field(default_factory=dict)
    default_request_config: dict[str, Any] = field(default_factory=dict)
    supported_accelerators: list[str] = field(default_factory=list)
    supports_auto_fallback: bool = False


@dataclass(slots=True)
class RuntimeRegisterDTO:
    request_id: str
    executor_id: str
    version: str
    plugins: list[RuntimePluginCapabilityDTO] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeHeartbeatDTO:
    request_id: str
    executor_id: str
    busy: bool
    current_task_id: str
    resources: dict[str, Any] = field(default_factory=dict)
