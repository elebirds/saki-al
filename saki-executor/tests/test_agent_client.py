import asyncio

import pytest

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.registry import PluginRegistry


def _build_client(tmp_path):
    registry = PluginRegistry()
    registry.load_builtin()
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = JobManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)
    return AgentClient(plugin_registry=registry, job_manager=manager)


@pytest.mark.anyio
async def test_error_message_resolves_pending_request_with_error(tmp_path):
    client = _build_client(tmp_path)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    client._pending["req-1"] = future  # noqa: SLF001

    await client._handle_incoming(  # noqa: SLF001
        {
            "type": "error",
            "request_id": "err-1",
            "reply_to": "req-1",
            "code": "INTERNAL",
            "message": "boom",
            "details": {"reason": "boom"},
        }
    )

    result = await asyncio.wait_for(future, timeout=1)
    assert result["error"] == "boom"
    assert result["code"] == "INTERNAL"

