from __future__ import annotations

from datetime import datetime
from typing import Any

from saki_api.models.l3.runtime_executor import RuntimeExecutor


PLUGIN_COMPARE_FIELDS = (
    "display_name",
    "version",
    "supported_job_types",
    "supported_strategies",
    "request_config_schema",
    "default_request_config",
)


def _normalize_text_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values = {str(item).strip() for item in raw if str(item).strip()}
    return sorted(values)


def extract_executor_plugins(raw_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = dict(raw_payload or {})
    raw_plugins = payload.get("plugins")
    if not isinstance(raw_plugins, list):
        return []

    plugins: list[dict[str, Any]] = []
    for item in raw_plugins:
        if not isinstance(item, dict):
            continue
        plugin_id = str(item.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        display_name = str(item.get("display_name") or plugin_id).strip() or plugin_id
        plugins.append(
            {
                "plugin_id": plugin_id,
                "display_name": display_name,
                "version": str(item.get("version") or ""),
                "supported_job_types": _normalize_text_list(item.get("supported_job_types")),
                "supported_strategies": _normalize_text_list(item.get("supported_strategies")),
                "request_config_schema": dict(item.get("request_config_schema") or {}),
                "default_request_config": dict(item.get("default_request_config") or {}),
            }
        )
    return plugins


def aggregate_runtime_plugins(executors: list[RuntimeExecutor]) -> list[dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}

    for executor in executors:
        plugins = extract_executor_plugins(executor.plugin_ids or {})
        is_online = bool(executor.is_online)
        status = str(executor.status or "")
        is_available = is_online and status not in {"busy", "reserved", "offline"}
        seen_at: datetime | None = executor.last_seen_at

        for plugin in plugins:
            plugin_id = plugin["plugin_id"]
            row = catalog.get(plugin_id)
            if row is None:
                row = {
                    **plugin,
                    "executors_total": 0,
                    "executors_online": 0,
                    "executors_available": 0,
                    "availability_rate": 0.0,
                    "has_conflict": False,
                    "conflict_fields": [],
                    "_latest_seen": seen_at,
                }
                catalog[plugin_id] = row
            else:
                mismatch = [
                    field_name
                    for field_name in PLUGIN_COMPARE_FIELDS
                    if row.get(field_name) != plugin.get(field_name)
                ]
                if mismatch:
                    row["has_conflict"] = True
                    row["conflict_fields"] = sorted(set(row["conflict_fields"]) | set(mismatch))

                latest_seen = row.get("_latest_seen")
                if latest_seen is None or (seen_at is not None and seen_at >= latest_seen):
                    for field_name in PLUGIN_COMPARE_FIELDS:
                        row[field_name] = plugin.get(field_name)
                    row["_latest_seen"] = seen_at

            row["executors_total"] += 1
            if is_online:
                row["executors_online"] += 1
            if is_available:
                row["executors_available"] += 1

    items: list[dict[str, Any]] = []
    for plugin_id in sorted(catalog.keys()):
        row = catalog[plugin_id]
        total = int(row.get("executors_total") or 0)
        available = int(row.get("executors_available") or 0)
        row["availability_rate"] = (available / total) if total > 0 else 0.0
        row.pop("_latest_seen", None)
        items.append(row)
    return items
