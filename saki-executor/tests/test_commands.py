import asyncio

import pytest

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.commands.server import CommandServer
from saki_executor.core.logging import get_log_level
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.registry import PluginRegistry


def _build_command_server(tmp_path):
    registry = PluginRegistry()
    registry.load_builtin()
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = JobManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)
    client = AgentClient(plugin_registry=registry, job_manager=manager)
    shutdown = asyncio.Event()
    command_server = CommandServer(
        job_manager=manager,
        plugin_registry=registry,
        client=client,
        shutdown_event=shutdown,
    )
    return command_server, shutdown, manager, client


@pytest.mark.anyio
async def test_quit_command_sets_shutdown_event(tmp_path):
    command_server, shutdown, _, _ = _build_command_server(tmp_path)
    assert not shutdown.is_set()
    await command_server.execute("quit")
    assert shutdown.is_set()


@pytest.mark.anyio
async def test_loglevel_command_updates_loguru_level(tmp_path):
    command_server, _, _, _ = _build_command_server(tmp_path)
    await command_server.execute("loglevel DEBUG")
    assert get_log_level() == "DEBUG"


@pytest.mark.anyio
async def test_connect_disconnect_commands_control_transport(tmp_path):
    command_server, _, _, client = _build_command_server(tmp_path)
    await command_server.execute("disconnect")
    assert client.transport_snapshot()["connect_enabled"] is False
    await command_server.execute("connect")
    assert client.transport_snapshot()["connect_enabled"] is True
