from __future__ import annotations

import asyncio

import pytest

import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import RuntimeControlService, _RuntimeStreamState
from saki_api.grpc_gen import runtime_control_pb2 as pb


def _build_stream_state() -> _RuntimeStreamState:
    return _RuntimeStreamState(outbox=asyncio.Queue())


@pytest.mark.anyio
async def test_handle_register_missing_executor_returns_error():
    service = RuntimeControlService()
    state = _build_stream_state()

    response = await service._handle_message(  # noqa: SLF001
        message=pb.RuntimeMessage(register=pb.Register(request_id="r1", executor_id="", version="1.0.0")),
        state=state,
    )

    assert response is not None
    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "invalid_register"


@pytest.mark.anyio
async def test_handle_register_success_calls_dispatcher(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()

    captured = {}

    async def fake_register_executor(*, executor_id, version, plugin_payloads, resources):
        captured["executor_id"] = executor_id
        captured["version"] = version
        captured["plugin_payloads"] = plugin_payloads
        captured["resources"] = resources

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register_executor", fake_register_executor)

    response = await service._handle_message(  # noqa: SLF001
        message=pb.RuntimeMessage(
            register=pb.Register(
                request_id="r2",
                executor_id="executor-1",
                version="1.0.0",
                plugins=[pb.PluginCapability(plugin_id="demo_det_v1", version="0.1.0")],
            )
        ),
        state=state,
    )

    assert response is not None
    assert response.WhichOneof("payload") == "ack"
    assert response.ack.type == pb.ACK_TYPE_REGISTER
    assert response.ack.reason == pb.ACK_REASON_REGISTERED
    assert captured["executor_id"] == "executor-1"
    assert state.executor_id == "executor-1"


@pytest.mark.anyio
async def test_handle_heartbeat_conflict_returns_error(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()
    state.executor_id = "executor-a"

    async def fake_handle_heartbeat(**_kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "handle_heartbeat", fake_handle_heartbeat)

    response = await service._handle_message(  # noqa: SLF001
        message=pb.RuntimeMessage(
            heartbeat=pb.Heartbeat(
                request_id="hb-1",
                executor_id="executor-b",
                busy=True,
                current_task_id="task-1",
            )
        ),
        state=state,
    )

    assert response is not None
    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "executor_id_conflict"


@pytest.mark.anyio
async def test_handle_heartbeat_success_updates_dispatcher(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()

    calls = []

    async def fake_handle_heartbeat(*, executor_id, busy, current_task_id, resources):
        calls.append((executor_id, busy, current_task_id, resources))

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "handle_heartbeat", fake_handle_heartbeat)

    response = await service._handle_message(  # noqa: SLF001
        message=pb.RuntimeMessage(
            heartbeat=pb.Heartbeat(
                request_id="hb-2",
                executor_id="executor-c",
                busy=True,
                current_task_id="task-2",
                resources=pb.ResourceSummary(gpu_count=1, cpu_workers=4, memory_mb=2048),
            )
        ),
        state=state,
    )

    assert response is not None
    assert response.WhichOneof("payload") == "ack"
    assert response.ack.reason == pb.ACK_REASON_ACCEPTED
    assert calls and calls[0][0] == "executor-c"
    assert calls[0][2] == "task-2"
