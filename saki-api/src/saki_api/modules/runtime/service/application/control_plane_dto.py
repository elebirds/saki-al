"""DTOs for runtime control-plane ingress messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeDataRequestDTO:
    request_id: str
    step_id: str
    query_type: int
    project_id: uuid.UUID
    commit_id: uuid.UUID
    limit: int
    offset: int
    preferred_chunk_bytes: int
    max_uncompressed_bytes: int


@dataclass(slots=True)
class RuntimeUploadTicketRequestDTO:
    request_id: str
    step_id: str
    artifact_name: str
    content_type: str


@dataclass(slots=True)
class RuntimePluginCapabilityDTO:
    plugin_id: str
    version: str = ""
    supported_step_types: list[str] = field(default_factory=list)
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
    node_id: str
    version: str
    runtime_kind: str = ""
    plugins: list[RuntimePluginCapabilityDTO] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    hardware_profile: dict[str, Any] = field(default_factory=dict)
    mps_stability_profile: dict[str, Any] = field(default_factory=dict)
    kernel_compat_flags: dict[str, Any] = field(default_factory=dict)
    health_status: str = ""
    health_detail: dict[str, Any] = field(default_factory=dict)
    uptime_sec: int = 0


@dataclass(slots=True)
class RuntimeHeartbeatDTO:
    request_id: str
    executor_id: str
    node_id: str
    busy: bool
    current_step_id: str
    resources: dict[str, Any] = field(default_factory=dict)
    health_status: str = ""
    health_detail: dict[str, Any] = field(default_factory=dict)
    uptime_sec: int = 0
