from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from saki_api.modules.runtime.domain.runtime_executor import RuntimeExecutor

PLUGIN_COMPARE_FIELDS = (
    "display_name",
    "version",
    "supported_task_types",
    "supported_strategies",
    "supported_accelerators",
    "supports_auto_fallback",
    "request_config_schema",
)


@dataclass(slots=True)
class RuntimePluginCapabilityVO:
    plugin_id: str
    display_name: str
    version: str
    supported_task_types: list[str] = field(default_factory=list)
    supported_strategies: list[str] = field(default_factory=list)
    supported_accelerators: list[str] = field(default_factory=list)
    supports_auto_fallback: bool = True
    request_config_schema: dict[str, Any] = field(default_factory=dict)
    executors_total: int = 0
    executors_online: int = 0
    executors_available: int = 0
    availability_rate: float = 0.0
    has_conflict: bool = False
    conflict_fields: list[str] = field(default_factory=list)


def _normalize_text_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values = {str(item).strip() for item in raw if str(item).strip()}
    return sorted(values)


def extract_executor_plugins(raw_payload: dict[str, Any] | None) -> list[RuntimePluginCapabilityVO]:
    payload = dict(raw_payload or {})
    raw_plugins = payload.get("plugins")
    if not isinstance(raw_plugins, list):
        return []

    plugins: list[RuntimePluginCapabilityVO] = []
    for item in raw_plugins:
        if not isinstance(item, dict):
            continue
        plugin_id = str(item.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        display_name = str(item.get("display_name") or plugin_id).strip() or plugin_id
        plugins.append(
            RuntimePluginCapabilityVO(
                plugin_id=plugin_id,
                display_name=display_name,
                version=str(item.get("version") or ""),
                supported_task_types=_normalize_text_list(item.get("supported_task_types")),
                supported_strategies=_normalize_text_list(item.get("supported_strategies")),
                supported_accelerators=_normalize_text_list(item.get("supported_accelerators")),
                supports_auto_fallback=bool(item.get("supports_auto_fallback", True)),
                request_config_schema=dict(item.get("request_config_schema") or {}),
            )
        )
    return plugins


def aggregate_runtime_plugins(executors: list[RuntimeExecutor]) -> list[RuntimePluginCapabilityVO]:
    catalog: dict[str, RuntimePluginCapabilityVO] = {}
    latest_seen_by_plugin: dict[str, datetime | None] = {}

    for executor in executors:
        plugins = extract_executor_plugins(executor.plugin_ids or {})
        is_online = bool(executor.is_online)
        status = str(executor.status or "")
        is_available = is_online and status not in {"busy", "reserved", "offline"}
        seen_at: datetime | None = executor.last_seen_at

        for plugin in plugins:
            plugin_id = plugin.plugin_id
            row = catalog.get(plugin_id)
            if row is None:
                row = RuntimePluginCapabilityVO(**asdict(plugin))
                catalog[plugin_id] = row
                latest_seen_by_plugin[plugin_id] = seen_at
            else:
                mismatch = [
                    field_name
                    for field_name in PLUGIN_COMPARE_FIELDS
                    if getattr(row, field_name) != getattr(plugin, field_name)
                ]
                if mismatch:
                    row.has_conflict = True
                    row.conflict_fields = sorted(set(row.conflict_fields) | set(mismatch))

                latest_seen = latest_seen_by_plugin.get(plugin_id)
                if latest_seen is None or (seen_at is not None and seen_at >= latest_seen):
                    for field_name in PLUGIN_COMPARE_FIELDS:
                        setattr(row, field_name, getattr(plugin, field_name))
                    latest_seen_by_plugin[plugin_id] = seen_at

            row.executors_total += 1
            if is_online:
                row.executors_online += 1
            if is_available:
                row.executors_available += 1

    items: list[RuntimePluginCapabilityVO] = []
    for plugin_id in sorted(catalog.keys()):
        row = catalog[plugin_id]
        total = int(row.executors_total)
        available = int(row.executors_available)
        row.availability_rate = (available / total) if total > 0 else 0.0
        items.append(row)
    return items
