from __future__ import annotations

import asyncio
import select
import shlex
import sys
from typing import TYPE_CHECKING

from loguru import logger

from saki_executor.core.config import settings
from saki_executor.core.logging import set_log_level, get_log_level

if TYPE_CHECKING:
    from saki_executor.agent.client import AgentClient
    from saki_executor.steps.manager import TaskManager
    from saki_executor.plugins.registry import PluginRegistry


class CommandServer:
    def __init__(
            self,
            *,
            task_manager: "TaskManager",
            plugin_registry: "PluginRegistry",
            client: "AgentClient",
            shutdown_event: asyncio.Event,
    ) -> None:
        self.task_manager = task_manager
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
                logger.error("读取命令失败: {}", exc)
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
                logger.exception("执行命令失败: {}", command)

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

        if command in {"refresh-hw", "refresh_hw", "refresh-hardware"}:
            await self._refresh_hardware()
            return

        if command in {"connect", "cn"}:
            await self.client.connect()
            return

        if command in {"disconnect", "dc"}:
            force = any(arg in {"--force", "-f"} for arg in args)
            await self.client.disconnect(force=force)
            return

        if command == "stop":
            await self._stop_task(args)
            return

        if command in {"loglevel", "ll"}:
            self._set_log_level(args)
            return

        if command in {"quit", "exit"}:
            logger.info("收到退出命令，准备关闭 executor。")
            self.shutdown_event.set()
            return

        logger.warning("未知命令: {}。输入 help 查看可用命令。", command_text)

    def _print_help(self) -> None:
        logger.info(
            "可用命令:\n"
            "  help                 查看帮助\n"
            "  status               查看当前执行器状态\n"
            "  plugins              查看已加载插件\n"
            "  refresh-hw           手动刷新宿主硬件探测缓存\n"
            "  connect              启用并发起连接\n"
            "  disconnect [--force] 断开并暂停连接（任务运行中默认拒绝，--force 会先 stop）\n"
            "  stop [task_id]       停止当前任务或指定 task_id\n"
            "  loglevel <LEVEL>     调整日志级别（DEBUG/INFO/WARNING/ERROR）\n"
            "  loglevel             查看当前日志级别\n"
            "  quit | exit          退出执行器进程"
        )

    def _print_status(self) -> None:
        runtime_status = self.task_manager.status_snapshot()
        transport_status = self.client.transport_snapshot()
        logger.info(
            "执行器状态:\n"
            "  executor_state={}\n"
            "  busy={}\n"
            "  current_task_id={}\n"
            "  last_task_id={}\n"
            "  last_task_status={}\n"
            "  running={}\n"
            "  connected={}\n"
            "  connect_enabled={}\n"
            "  pending_requests={}\n"
            "  outbound_queue={}\n"
            "  last_heartbeat_ts={}\n"
            "  host_capability_last_probe_ts={}\n"
            "  log_level={}",
            runtime_status["executor_state"],
            runtime_status["busy"],
            runtime_status["current_task_id"],
            runtime_status["last_task_id"],
            runtime_status["last_task_status"],
            transport_status["running"],
            transport_status["connected"],
            transport_status["connect_enabled"],
            transport_status["pending_requests"],
            transport_status["outbox_size"],
            transport_status["last_heartbeat_ts"],
            runtime_status["host_capability_last_probe_ts"],
            get_log_level(),
        )

    async def _refresh_hardware(self) -> None:
        snapshot = await asyncio.to_thread(self.task_manager.refresh_host_capability)
        backends = ["cpu"]
        if snapshot.gpus:
            backends.insert(0, "cuda")
        if snapshot.metal_available:
            backends.insert(1 if "cuda" in backends else 0, "mps")
        logger.info(
            "宿主硬件探测缓存已刷新 backends={} cpu_workers={} memory_mb={} gpu_count={}",
            backends,
            snapshot.cpu_workers,
            snapshot.memory_mb,
            len(snapshot.gpus),
        )

    def _print_plugins(self) -> None:
        plugins = self.plugin_registry.all()
        if not plugins:
            logger.info("当前未加载任何插件。")
            return
        plugin_lines = [
            f"  - {plugin.plugin_id} v{plugin.version} | task_types={plugin.supported_task_types} | strategies={plugin.supported_strategies}"
            for plugin in plugins
        ]
        logger.info("已加载插件:\n{}", "\n".join(plugin_lines))

    async def _stop_task(self, args: list[str]) -> None:
        task_id = args[0] if args else self.task_manager.current_task_id
        if not task_id:
            logger.warning("当前没有可停止的任务，请提供 task_id。")
            return
        stopped = await self.task_manager.stop_task(str(task_id))
        if stopped:
            logger.info("已发送停止请求，task_id={}", task_id)
        else:
            logger.warning("停止失败，task_id={} 未在运行或不可停止。", task_id)

    def _set_log_level(self, args: list[str]) -> None:
        if not args:
            logger.info("当前日志级别: {}", get_log_level())
            return
        level_name = args[0].upper()
        try:
            set_log_level(level_name)
        except ValueError:
            logger.warning("无效日志级别: {}", args[0])
            return
        logger.info("日志级别已更新为 {}", level_name)
