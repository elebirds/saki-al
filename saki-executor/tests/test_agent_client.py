import asyncio

import pytest

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
                reply_to="req-1",
                reason="boom",
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
    client.job_manager.current_task_id = "task-1"
    try:
        disconnected = await client.disconnect(force=False)
        assert disconnected is False
        assert client.transport_snapshot()["connect_enabled"] is True
    finally:
        busy_task.cancel()
        client.job_manager._task = None  # noqa: SLF001
        client.job_manager.current_task_id = None


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


@pytest.mark.anyio
async def test_disconnect_force_waits_for_stop_before_disconnect(tmp_path, monkeypatch):
    client = _build_client(tmp_path)
    monkeypatch.setattr("saki_executor.agent.client.settings.DISCONNECT_FORCE_WAIT_SEC", 1)

    busy_task = asyncio.create_task(asyncio.sleep(60))
    client.job_manager._task = busy_task  # noqa: SLF001
    client.job_manager.current_task_id = "task-force-1"
    stop_called: list[str] = []

    async def fake_stop(task_id: str) -> bool:
        stop_called.append(task_id)
        client.job_manager._task = None  # noqa: SLF001
        client.job_manager.current_task_id = None
        busy_task.cancel()
        return True

    client.job_manager.stop_task = fake_stop  # type: ignore[method-assign]

    disconnected = await client.disconnect(force=True)
    assert disconnected is True
    assert stop_called == ["task-force-1"]
    assert client.transport_snapshot()["connect_enabled"] is False


@pytest.mark.anyio
async def test_duplicate_assign_task_returns_cached_ack_without_reassign(tmp_path):
    client = _build_client(tmp_path)
    assign_calls: list[str] = []
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_assign_task(request_id: str, payload: dict):  # noqa: ARG001
        assign_calls.append(request_id)
        return True

    async def fake_send_message(message: pb.RuntimeMessage):
        sent_messages.append(message)

    client.job_manager.assign_task = fake_assign_task  # type: ignore[method-assign]
    client.send_message = fake_send_message  # type: ignore[method-assign]

    incoming = pb.RuntimeMessage(
        assign_task=pb.AssignTask(
            request_id="assign-dup-1",
            task=pb.TaskPayload(
                task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                job_id="11111111-1111-1111-1111-111111111111",
                project_id="22222222-2222-2222-2222-222222222222",
                loop_id="33333333-3333-3333-3333-333333333333",
                source_commit_id="44444444-4444-4444-4444-444444444444",
                task_type=pb.TRAIN,
                plugin_id="demo_det_v1",
                mode=pb.ACTIVE_LEARNING,
            ),
        )
    )

    await client._handle_incoming(incoming)  # noqa: SLF001
    await client._handle_incoming(incoming)  # noqa: SLF001

    assert assign_calls == ["assign-dup-1"]
    assert len(sent_messages) == 2
    assert sent_messages[0].ack.ack_for == "assign-dup-1"
    assert sent_messages[1].ack.ack_for == "assign-dup-1"
    assert sent_messages[0].SerializeToString() == sent_messages[1].SerializeToString()


@pytest.mark.anyio
async def test_duplicate_stop_task_returns_cached_ack_without_restop(tmp_path):
    client = _build_client(tmp_path)
    stop_calls: list[str] = []
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_stop_task(task_id: str):
        stop_calls.append(task_id)
        return True

    async def fake_send_message(message: pb.RuntimeMessage):
        sent_messages.append(message)

    client.job_manager.stop_task = fake_stop_task  # type: ignore[method-assign]
    client.send_message = fake_send_message  # type: ignore[method-assign]

    incoming = pb.RuntimeMessage(
        stop_task=pb.StopTask(
            request_id="stop-dup-1",
            task_id="task-dup-1",
            reason="manual",
        )
    )

    await client._handle_incoming(incoming)  # noqa: SLF001
    await client._handle_incoming(incoming)  # noqa: SLF001

    assert stop_calls == ["task-dup-1"]
    assert len(sent_messages) == 2
    assert sent_messages[0].ack.ack_for == "stop-dup-1"
    assert sent_messages[1].ack.ack_for == "stop-dup-1"
    assert sent_messages[0].SerializeToString() == sent_messages[1].SerializeToString()
