import asyncio

import pytest

from saki_executor.agent import codec as runtime_codec
from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
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
        pb.RuntimeMessage(
            error=pb.Error(
                request_id="err-1",
                code="INTERNAL",
                message="boom",
                details=runtime_codec.dict_to_struct({"reply_to": "req-1", "reason": "boom"}),
            )
        )
    )

    result = await asyncio.wait_for(future, timeout=1)
    assert result.WhichOneof("payload") == "error"
    assert result.error.code == "INTERNAL"
    assert result.error.message == "boom"


@pytest.mark.anyio
async def test_disconnect_rejects_when_busy_without_force(tmp_path):
    client = _build_client(tmp_path)
    busy_task = asyncio.create_task(asyncio.sleep(60))
    client.job_manager._task = busy_task  # noqa: SLF001
    client.job_manager.current_job_id = "job-1"
    try:
        disconnected = await client.disconnect(force=False)
        assert disconnected is False
        assert client.transport_snapshot()["connect_enabled"] is True
    finally:
        busy_task.cancel()
        client.job_manager._task = None  # noqa: SLF001
        client.job_manager.current_job_id = None


@pytest.mark.anyio
async def test_disconnect_force_disables_connection_and_fails_pending(tmp_path):
    client = _build_client(tmp_path)
    loop = asyncio.get_running_loop()
    pending_future = loop.create_future()
    client._pending["req-2"] = pending_future  # noqa: SLF001

    disconnected = await client.disconnect(force=True)
    assert disconnected is True
    assert client.transport_snapshot()["connect_enabled"] is False
    assert pending_future.done() is True
    with pytest.raises(RuntimeError):
        pending_future.result()
