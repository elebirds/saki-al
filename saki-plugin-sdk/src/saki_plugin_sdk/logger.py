"""插件统一日志服务。

提供带插件上下文前缀的日志记录功能。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger as _logger


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
        self._level = level

    def _format_msg(self, message: str) -> str:
        """格式化消息，添加插件上下文前缀。"""
        prefix = f"[{self.plugin_id}"
        if self.step_id:
            prefix += f"|{self.step_id}"
        prefix += "]"
        return f"{prefix} {message}"

    def debug(self, message: str, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志。"""
        _logger.debug(self._format_msg(message), **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """记录 INFO 级别日志。"""
        _logger.info(self._format_msg(message), **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """记录 WARNING 级别日志。"""
        _logger.warning(self._format_msg(message), **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """记录 ERROR 级别日志。"""
        _logger.error(self._format_msg(message), **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """记录 CRITICAL 级别日志。"""
        _logger.critical(self._format_msg(message), **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        """记录异常日志，自动包含堆栈信息。"""
        _logger.exception(self._format_msg(message), **kwargs)
