from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_CURRENT_LEVEL: str = "INFO"
_LOG_FILE_PATH: Path | None = None
_LOG_ROTATION_BYTES: int = 20 * 1024 * 1024
_LOG_RETENTION_FILES: int = 5
_LOG_COLOR_MODE: str = "auto"


def _normalize_level(level: str) -> str:
    normalized = (level or "INFO").upper()
    valid_levels = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    if normalized not in valid_levels:
        raise ValueError(f"invalid log level: {level}")
    return normalized


def _normalize_color_mode(mode: str) -> str:
    normalized = (mode or "auto").strip().lower()
    if normalized not in {"auto", "on", "off"}:
        raise ValueError(f"invalid log color mode: {mode}")
    return normalized


def _resolve_colorize(mode: str, stream) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _apply_sinks(level: str) -> None:
    logger.remove()

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        "<level>{level: <8}</level> "
        "<magenta>{process.id}</magenta> "
        "<white>---</white> "
        "<cyan>[{thread.name: <14}]</cyan> "
        "<blue>{name: <36}</blue> "
        "<white>:</white> "
        "<level>{message}</level>"
    )
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}"
    console_stream = sys.stdout

    logger.add(
        console_stream,
        level=level,
        format=console_format,
        backtrace=False,
        diagnose=False,
        colorize=_resolve_colorize(_LOG_COLOR_MODE, console_stream),
    )

    if _LOG_FILE_PATH is not None:
        _LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(_LOG_FILE_PATH),
            level=level,
            format=file_format,
            rotation=max(1, int(_LOG_ROTATION_BYTES)),
            retention=max(1, int(_LOG_RETENTION_FILES)),
            backtrace=False,
            diagnose=False,
            enqueue=False,
            encoding="utf-8",
        )


def setup_logging(
        *,
        level: str,
        log_dir: str,
        log_file_name: str,
        max_bytes: int,
        backup_count: int,
        color_mode: str = "auto",
) -> None:
    global _CURRENT_LEVEL, _LOG_FILE_PATH, _LOG_ROTATION_BYTES, _LOG_RETENTION_FILES, _LOG_COLOR_MODE
    _CURRENT_LEVEL = _normalize_level(level)
    _LOG_FILE_PATH = Path(log_dir) / log_file_name
    _LOG_ROTATION_BYTES = max(1, int(max_bytes))
    _LOG_RETENTION_FILES = max(1, int(backup_count))
    _LOG_COLOR_MODE = _normalize_color_mode(color_mode)
    _apply_sinks(_CURRENT_LEVEL)


def set_log_level(level: str) -> None:
    global _CURRENT_LEVEL
    _CURRENT_LEVEL = _normalize_level(level)
    _apply_sinks(_CURRENT_LEVEL)


def get_log_level() -> str:
    return _CURRENT_LEVEL
