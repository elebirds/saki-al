import asyncio
import signal
from contextlib import suppress

from loguru import logger

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.commands.server import CommandServer
from saki_executor.core.config import settings
from saki_executor.core.logging import setup_logging
from saki_executor.steps.manager import StepManager
from saki_executor.plugins.registry import PluginRegistry


async def run() -> None:
    setup_logging(
        level=settings.LOG_LEVEL,
        log_dir=settings.LOG_DIR,
        log_file_name=settings.LOG_FILE_NAME,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
        color_mode=settings.LOG_COLOR_MODE,
    )

    registry = PluginRegistry()
    registry.load_builtin()

    cache = AssetCache(root_dir=settings.CACHE_DIR, max_bytes=settings.CACHE_MAX_BYTES)
    manager = StepManager(
        runs_dir=settings.RUNS_DIR,
        cache=cache,
        plugin_registry=registry,
    )
    client = AgentClient(plugin_registry=registry, step_manager=manager)
    manager.set_transport(client.send_message, client.request_message)

    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, shutdown_event.set)

    command_server = CommandServer(
        step_manager=manager,
        plugin_registry=registry,
        client=client,
        shutdown_event=shutdown_event,
    )

    logger.info(
        "saki-executor 启动完成 executor_id={} version={} grpc_target={} plugins={}",
        settings.EXECUTOR_ID,
        settings.EXECUTOR_VERSION,
        settings.API_GRPC_TARGET,
        [plugin.plugin_id for plugin in registry.all()],
    )

    client_task = asyncio.create_task(client.run(shutdown_event=shutdown_event), name="grpc-client")
    command_task = asyncio.create_task(command_server.run(), name="command-server")

    def _on_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("任务异常退出 task={} error={}", task.get_name(), exc)
        shutdown_event.set()

    client_task.add_done_callback(_on_task_done)
    command_task.add_done_callback(_on_task_done)

    await shutdown_event.wait()
    logger.info("收到关闭信号，准备停止 executor。")

    for task in (client_task, command_task):
        if not task.done():
            task.cancel()
    for task in (client_task, command_task):
        with suppress(asyncio.CancelledError):
            await task

    logger.info("executor 已退出。")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
