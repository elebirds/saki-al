import asyncio
import signal
from contextlib import suppress

from loguru import logger

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.commands.server import CommandServer
from saki_executor.core.config import settings
from saki_executor.core.logging import setup_logging
from saki_executor.runtime.capability.host_capability_cache import HostCapabilityCache
from saki_executor.steps.manager import TaskManager
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.updater import RuntimeUpdater


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
    registry.discover_plugins(settings.PLUGINS_DIR)

    host_capability_cache = HostCapabilityCache(
        cpu_workers=settings.CPU_WORKERS,
        memory_mb=settings.MEMORY_MB,
    )
    host_snapshot = host_capability_cache.refresh()

    cache = AssetCache(
        root_dir=settings.CACHE_DIR,
        max_bytes=settings.CACHE_MAX_BYTES,
        download_concurrency=settings.ASSET_DOWNLOAD_CONCURRENCY,
        http_timeout_sec=settings.HTTP_TIMEOUT_SEC,
    )
    manager = TaskManager(
        runs_dir=settings.RUNS_DIR,
        cache=cache,
        plugin_registry=registry,
        round_shared_cache_enabled=settings.ROUND_SHARED_CACHE_ENABLED,
        strict_train_model_handoff=settings.STRICT_TRAIN_MODEL_HANDOFF,
        host_capability_cache=host_capability_cache,
    )
    shutdown_event = asyncio.Event()
    fatal_errors: list[BaseException] = []

    def _report_fatal_error(exc: BaseException) -> None:
        if not fatal_errors:
            fatal_errors.append(exc)
        shutdown_event.set()

    manager.set_fatal_error_callback(_report_fatal_error)
    runtime_updater = RuntimeUpdater(
        plugin_registry=registry,
        host_capability_cache=host_capability_cache,
        shutdown_event=shutdown_event,
    )
    client = AgentClient(plugin_registry=registry, task_manager=manager, runtime_updater=runtime_updater)
    manager.set_transport(client.send_message, client.request_message)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, shutdown_event.set)

    command_server = CommandServer(
        task_manager=manager,
        plugin_registry=registry,
        client=client,
        shutdown_event=shutdown_event,
    )

    host_backends = ["cpu"]
    if host_snapshot.gpus:
        host_backends.insert(0, "cuda")
    if host_snapshot.metal_available:
        host_backends.insert(1 if "cuda" in host_backends else 0, "mps")

    logger.info(
        "saki-executor 启动完成 executor_id={} version={} grpc_target={} plugins={} host_backends={}",
        settings.EXECUTOR_ID,
        settings.EXECUTOR_VERSION,
        settings.API_GRPC_TARGET,
        [plugin.plugin_id for plugin in registry.all()],
        host_backends,
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
    logger.info("收到关闭信号，准备停止执行器。")

    with suppress(Exception):
        await client.shutdown(force=True)

    for task in (client_task, command_task):
        if not task.done():
            task.cancel()
    for task in (client_task, command_task):
        with suppress(asyncio.CancelledError):
            await task
    with suppress(Exception):
        await cache.aclose()

    logger.info("执行器已退出。")
    if fatal_errors:
        raise fatal_errors[0]

    for task in (client_task, command_task):
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            raise exc


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
