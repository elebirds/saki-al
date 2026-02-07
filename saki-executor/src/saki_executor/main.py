import asyncio

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.core.config import settings
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.registry import PluginRegistry


async def run() -> None:
    registry = PluginRegistry()
    registry.load_builtin()

    cache = AssetCache(root_dir=settings.CACHE_DIR, max_bytes=settings.CACHE_MAX_BYTES)
    manager = JobManager(
        runs_dir=settings.RUNS_DIR,
        cache=cache,
        plugin_registry=registry,
    )
    client = AgentClient(plugin_registry=registry, job_manager=manager)
    manager.set_transport(client.send_message, client.request_message)
    await client.run()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
