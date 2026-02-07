from __future__ import annotations

import asyncio
import logging
import select
import shlex
import sys
from typing import TYPE_CHECKING

from saki_executor.core.config import settings

if TYPE_CHECKING:
    from saki_executor.agent.client import AgentClient
    from saki_executor.jobs.manager import JobManager
    from saki_executor.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


class CommandServer:
    def __init__(
            self,
            *,
            job_manager: "JobManager",
            plugin_registry: "PluginRegistry",
            client: "AgentClient",
            shutdown_event: asyncio.Event,
    ) -> None:
        self.job_manager = job_manager
        self.plugin_registry = plugin_registry
        self.client = client
        self.shutdown_event = shutdown_event

    async def run(self) -> None:
        if not settings.ENABLE_COMMAND_STDIN:
            logger.info("命令系统已禁用（ENABLE_COMMAND_STDIN=false）")
            await self.shutdown_event.wait()
            return

        logger.info("命令系统已启动，可输入 help 查看可用命令。")
        while not self.shutdown_event.is_set():
            try:
                raw = await asyncio.to_thread(self._readline_with_timeout, 0.5)
            except Exception as exc:
                logger.error("读取命令失败: %s", exc)
                await asyncio.sleep(1)
                continue

            if raw is None:
                await asyncio.sleep(0.2)
                continue
            if raw == "":
                await asyncio.sleep(0.5)
                continue

            command = raw.strip()
            if not command:
                continue

            try:
                await self.execute(command)
            except Exception:
                logger.exception("执行命令失败: %s", command)

    @staticmethod
    def _readline_with_timeout(timeout_sec: float) -> str | None:
        readable, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not readable:
            return None
        return sys.stdin.readline()

    async def execute(self, command_text: str) -> None:
        parts = shlex.split(command_text)
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        if command in {"help", "h", "?"}:
            self._print_help()
            return

        if command in {"status", "st"}:
            self._print_status()
            return

        if command in {"plugins", "pl"}:
            self._print_plugins()
            return

        if command in {"connect", "cn"}:
            await self.client.connect()
            return

        if command in {"disconnect", "dc"}:
            await self.client.disconnect()
            return

        if command == "stop":
            await self._stop_job(args)
            return

        if command in {"loglevel", "ll"}:
            self._set_log_level(args)
            return

        if command in {"quit", "exit"}:
            logger.info("收到退出命令，准备关闭 executor。")
            self.shutdown_event.set()
            return

        logger.warning("未知命令: %s。输入 help 查看可用命令。", command_text)

    def _print_help(self) -> None:
        logger.info(
            "可用命令:\n"
            "  help                 查看帮助\n"
            "  status               查看当前执行器状态\n"
            "  plugins              查看已加载插件\n"
            "  connect              启用并发起连接\n"
            "  disconnect           断开并暂停连接\n"
            "  stop [job_id]        停止当前任务或指定 job_id\n"
            "  loglevel <LEVEL>     调整日志级别（DEBUG/INFO/WARNING/ERROR）\n"
            "  quit | exit          退出执行器进程"
        )

    def _print_status(self) -> None:
        job_status = self.job_manager.status_snapshot()
        transport_status = self.client.transport_snapshot()
        logger.info(
            "执行器状态:\n"
            "  executor_state=%s\n"
            "  busy=%s\n"
            "  current_job_id=%s\n"
            "  last_job_id=%s\n"
            "  last_job_status=%s\n"
            "  running=%s\n"
            "  connected=%s\n"
            "  connect_enabled=%s\n"
            "  pending_requests=%s\n"
            "  outbound_queue=%s\n"
            "  last_heartbeat_ts=%s",
            job_status["executor_state"],
            job_status["busy"],
            job_status["current_job_id"],
            job_status["last_job_id"],
            job_status["last_job_status"],
            transport_status["running"],
            transport_status["connected"],
            transport_status["connect_enabled"],
            transport_status["pending_requests"],
            transport_status["outbox_size"],
            transport_status["last_heartbeat_ts"],
        )

    def _print_plugins(self) -> None:
        plugins = self.plugin_registry.all()
        if not plugins:
            logger.info("当前未加载任何插件。")
            return
        plugin_lines = [
            f"  - {plugin.plugin_id} v{plugin.version} | job_types={plugin.supported_job_types} | strategies={plugin.supported_strategies}"
            for plugin in plugins
        ]
        logger.info("已加载插件:\n%s", "\n".join(plugin_lines))

    async def _stop_job(self, args: list[str]) -> None:
        job_id = args[0] if args else self.job_manager.current_job_id
        if not job_id:
            logger.warning("当前没有可停止的任务，请提供 job_id。")
            return
        stopped = await self.job_manager.stop_job(str(job_id))
        if stopped:
            logger.info("已发送停止请求，job_id=%s", job_id)
        else:
            logger.warning("停止失败，job_id=%s 未在运行或不可停止。", job_id)

    def _set_log_level(self, args: list[str]) -> None:
        if not args:
            logger.warning("请提供日志级别，例如: loglevel DEBUG")
            return
        level_name = args[0].upper()
        level_value = getattr(logging, level_name, None)
        if not isinstance(level_value, int):
            logger.warning("无效日志级别: %s", args[0])
            return

        root = logging.getLogger()
        root.setLevel(level_value)
        for handler in root.handlers:
            handler.setLevel(level_value)
        logger.info("日志级别已更新为 %s", level_name)
