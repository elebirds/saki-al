"""插件统一日志服务。

提供带插件上下文前缀的日志记录功能。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Callable, Mapping

from loguru import logger as _logger

LogBridge = Callable[[dict[str, Any]], None]

_LOG_BRIDGE_CTX: ContextVar[LogBridge | None] = ContextVar("saki_plugin_log_bridge", default=None)
_LEVEL_WEIGHT = {
    "TRACE": 10,
    "DEBUG": 20,
    "INFO": 30,
    "SUCCESS": 35,
    "WARNING": 40,
    "ERROR": 50,
    "CRITICAL": 60,
}


def _normalize_level(level: str) -> str:
    normalized = str(level or "INFO").strip().upper()
    if normalized == "WARN":
        return "WARNING"
    if normalized not in _LEVEL_WEIGHT:
        return "INFO"
    return normalized


def set_log_bridge(bridge: LogBridge | None) -> Token[LogBridge | None]:
    """Set per-context structured log bridge for plugin logger."""
    return _LOG_BRIDGE_CTX.set(bridge)


def reset_log_bridge(token: Token[LogBridge | None]) -> None:
    """Reset per-context structured log bridge for plugin logger."""
    _LOG_BRIDGE_CTX.reset(token)


class PluginLogger:
    """统一的插件日志服务。

    为插件提供带上下文前缀的日志输出，方便在多插件环境中追踪日志来源。

    Parameters
    ----------
    plugin_id : str
        插件标识符，用作日志前缀。
    step_id : str | None
        可选的 step_id，用于区分不同的执行步骤。
    log_file : Path | None
        可选的日志文件路径（保留用于未来扩展）。
    level : str
        日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）。
    """

    def __init__(
        self,
        plugin_id: str,
        step_id: str | None = None,
        log_file: Path | None = None,
        level: str = "INFO",
    ) -> None:
        self.plugin_id = plugin_id
        self.step_id = step_id
        self._log_file = log_file
        self._level = _normalize_level(level)

    def _format_msg(self, message: str) -> str:
        """格式化消息，添加插件上下文前缀。"""
        prefix = f"[{self.plugin_id}"
        if self.step_id:
            prefix += f"|{self.step_id}"
        prefix += "]"
        return f"{prefix} {message}"

    def _should_log(self, level: str) -> bool:
        return _LEVEL_WEIGHT[_normalize_level(level)] >= _LEVEL_WEIGHT[self._level]

    def _bridge_or_fallback(self, level: str, payload: dict[str, Any]) -> None:
        bridge = _LOG_BRIDGE_CTX.get()
        if bridge is not None:
            try:
                bridge(payload)
                return
            except Exception:
                _logger.exception("plugin log bridge emit failed")
        text = str(payload.get("message") or "")
        if level == "DEBUG":
            _logger.debug(text)
        elif level == "INFO":
            _logger.info(text)
        elif level == "WARNING":
            _logger.warning(text)
        elif level == "ERROR":
            _logger.error(text)
        elif level == "CRITICAL":
            _logger.critical(text)
        else:
            _logger.info(text)

    def _normalize_args(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, Mapping):
            return {str(k): v for k, v in payload.items()}
        return {}

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        normalized_level = _normalize_level(level)
        if not self._should_log(normalized_level):
            return

        message_text = str(message or "")
        meta_payload = self._normalize_args(kwargs.pop("meta", {}))
        meta_payload.setdefault("source", "plugin_logger")
        meta_payload.setdefault("plugin_id", self.plugin_id)
        if self.step_id:
            meta_payload.setdefault("step_id", self.step_id)

        payload: dict[str, Any] = {
            "level": normalized_level,
            "message": self._format_msg(message_text),
            "raw_message": message_text,
            "meta": meta_payload,
        }
        message_key = kwargs.pop("message_key", None)
        if message_key is not None:
            text = str(message_key).strip()
            if text:
                payload["message_key"] = text
        message_args = kwargs.pop("message_args", None)
        if message_args is not None:
            payload["message_args"] = self._normalize_args(message_args)
        self._bridge_or_fallback(normalized_level, payload)

    def debug(self, message: str, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志。"""
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """记录 INFO 级别日志。"""
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """记录 WARNING 级别日志。"""
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """记录 ERROR 级别日志。"""
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """记录 CRITICAL 级别日志。"""
        self._log("CRITICAL", message, **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        """记录异常日志，自动包含堆栈信息。"""
        kwargs.setdefault("meta", {"exception": True})
        self._log("ERROR", message, **kwargs)
