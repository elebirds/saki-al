from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_LEVEL_WEIGHT: dict[str, int] = {
    "TRACE": 10,
    "DEBUG": 20,
    "INFO": 30,
    "WARNING": 40,
    "ERROR": 50,
    "CRITICAL": 60,
}

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
_ANSI_SINGLE_RE = re.compile(r"\x1b[@-Z\\-_]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_LOGURU_PREFIX_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+\|\s*(?P<level>[A-Z]+)\s*\|\s*[^|]+\|\s*(?P<message>.*)$"
)
_PY_LOGGING_PREFIX_RE = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*(?:-|\|)\s*)?"
    r"(?P<level>TRACE|DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\s*(?::|-|\|)\s*(?P<message>.*)$",
    re.IGNORECASE,
)
_SIMPLE_LEVEL_PREFIX_RE = re.compile(
    r"^\s*\[?(?P<level>TRACE|DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]?\s*(?::|-|\|)\s*(?P<message>.*)$",
    re.IGNORECASE,
)

_TRACEBACK_RE = re.compile(r"traceback\s*\(most recent call last\)", re.IGNORECASE)
_ERROR_TOKEN_RE = re.compile(r"\b(error|exception|fatal)\b", re.IGNORECASE)
_ERROR_FALSE_POSITIVE_RE = re.compile(r"\b(no|0)\s+(error|errors|exception|exceptions)\b", re.IGNORECASE)


def normalize_level(level: str | None, default: str = "INFO") -> str:
    value = str(level or default).strip().upper()
    if value == "WARN":
        return "WARNING"
    if value == "FATAL":
        return "CRITICAL"
    if value not in _LEVEL_WEIGHT:
        return normalize_level(default)
    return value


def strip_ansi_and_controls(text: str | None) -> str:
    value = str(text or "")
    value = value.replace("\r\n", "\n")
    # Treat carriage return as in-place line overwrite and keep only final segment.
    if "\r" in value:
        lines: list[str] = []
        for item in value.split("\n"):
            if "\r" in item:
                lines.append(item.split("\r")[-1])
            else:
                lines.append(item)
        value = "\n".join(lines)
    value = _ANSI_OSC_RE.sub("", value)
    value = _ANSI_CSI_RE.sub("", value)
    value = _ANSI_SINGLE_RE.sub("", value)
    value = _CONTROL_RE.sub("", value)
    return value


def _extract_embedded_level_and_message(message: str) -> tuple[str | None, str]:
    for pattern in (_LOGURU_PREFIX_RE, _PY_LOGGING_PREFIX_RE, _SIMPLE_LEVEL_PREFIX_RE):
        matched = pattern.match(message)
        if not matched:
            continue
        parsed_level = normalize_level(matched.group("level"), default="INFO")
        parsed_message = str(matched.group("message") or "").rstrip()
        return parsed_level, parsed_message
    return None, message.rstrip()


def _looks_like_error_message(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    if _TRACEBACK_RE.search(text):
        return True
    if _ERROR_FALSE_POSITIVE_RE.search(text):
        return False
    return bool(_ERROR_TOKEN_RE.search(text))


def normalize_log_payload(
    payload: Mapping[str, Any] | None,
    *,
    plugin_id: str,
    default_source: str,
    default_stream: str | None = None,
) -> dict[str, Any]:
    row = dict(payload or {})
    raw_message = str(row.get("raw_message") or row.get("message") or "").rstrip("\n")
    cleaned_message = strip_ansi_and_controls(str(row.get("message") or raw_message)).rstrip()

    parsed_level, stripped_message = _extract_embedded_level_and_message(cleaned_message)
    display_message = stripped_message if stripped_message else cleaned_message
    declared_level = normalize_level(str(row.get("level") or "").strip() or None, default="INFO")
    level = parsed_level or declared_level

    if _looks_like_error_message(display_message) and _LEVEL_WEIGHT[level] < _LEVEL_WEIGHT["ERROR"]:
        level = "ERROR"

    meta_raw = row.get("meta")
    meta = dict(meta_raw) if isinstance(meta_raw, Mapping) else {}
    meta.setdefault("source", default_source)
    meta.setdefault("plugin_id", plugin_id)
    if default_stream:
        meta.setdefault("stream", default_stream)
    tags_raw = meta.get("tags")
    if isinstance(tags_raw, list):
        tags = [str(item).strip() for item in tags_raw if str(item).strip()]
    else:
        tags = []
    if default_source not in tags:
        tags.append(default_source)
    if default_stream and default_stream not in tags:
        tags.append(default_stream)
    meta["tags"] = tags

    normalized: dict[str, Any] = {
        "level": level,
        "message": display_message,
        "raw_message": raw_message,
        "meta": meta,
    }

    message_key = row.get("message_key")
    if message_key is not None:
        key_text = str(message_key).strip()
        if key_text:
            normalized["message_key"] = key_text

    message_args = row.get("message_args")
    if isinstance(message_args, Mapping):
        normalized["message_args"] = {str(key): value for key, value in message_args.items()}

    return normalized


def normalize_stdio_log_line(*, raw_line: str, plugin_id: str, stream: str) -> dict[str, Any] | None:
    raw_message = str(raw_line or "").rstrip("\n")
    if not raw_message:
        return None

    default_level = "WARNING" if str(stream).lower() == "stderr" else "INFO"
    payload = normalize_log_payload(
        {
            "level": default_level,
            "message": raw_message,
            "raw_message": raw_message,
            "meta": {"stream": str(stream).lower()},
        },
        plugin_id=plugin_id,
        default_source="worker_stdio",
        default_stream=str(stream).lower(),
    )

    if _looks_like_error_message(payload["message"]) and _LEVEL_WEIGHT[payload["level"]] < _LEVEL_WEIGHT["ERROR"]:
        payload["level"] = "ERROR"

    if not str(payload.get("message") or "").strip() and not str(payload.get("raw_message") or "").strip():
        return None

    return payload
