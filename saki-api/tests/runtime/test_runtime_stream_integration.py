from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import grpc
import pytest
from google.protobuf.struct_pb2 import Struct

import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.core.config import settings
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_control_pb2_grpc as pb_grpc
from saki_api.grpc.runtime_control import RuntimeControlService


class _StreamClient:
    def __init__(self, target: str, token: str):
        self._queue: asyncio.Queue[pb.RuntimeMessage | None] = asyncio.Queue()
        self._channel = grpc.aio.insecure_channel(target)
        stub = pb_grpc.RuntimeControlStub(self._channel)
        self._call = stub.Stream(self._request_iter(), metadata=[("x-internal-token", token)])

    async def _request_iter(self) -> AsyncIterator[pb.RuntimeMessage]:
        while True:
            message = await self._queue.get()
            if message is None:
                break
            yield message

    async def send(self, message: pb.RuntimeMessage) -> None:
        await self._queue.put(message)

    async def recv(self, timeout: float = 2.0) -> pb.RuntimeMessage:
        message = await asyncio.wait_for(self._call.read(), timeout=timeout)
        if message == grpc.aio.EOF:
            raise EOFError("stream closed")
        return message

    async def close(self) -> None:
        await self._queue.put(None)
        await self._channel.close()


@pytest.mark.anyio
async def test_runtime_stream_e2e_happy_path(monkeypatch):
    service = RuntimeControlService()

    persisted_events: list[pb.JobEvent] = []
    persisted_results: list[pb.JobResult] = []
    heartbeats: list[tuple[str, bool, str]] = []
    ack_records: list[tuple[str, int, str | None]] = []
    mark_idle_records: list[tuple[str, str | None]] = []
    unregister_records: list[str] = []

    async def fake_persist_event(message: pb.JobEvent) -> None:
        persisted_events.append(message)

    async def fake_persist_result(message: pb.JobResult) -> None:
        persisted_results.append(message)

    async def fake_register(
            *,
            executor_id: str,
            queue: asyncio.Queue[pb.RuntimeMessage],
            version: str,
            plugin_ids: set[str],
            resources: dict[str, Any],
    ) -> None:
        async def _enqueue_assign() -> None:
            await asyncio.sleep(0.05)
            await queue.put(
                pb.RuntimeMessage(
                    assign_job=pb.AssignJob(
                        request_id="assign-req-1",
                        job=pb.JobPayload(
                            job_id="11111111-1111-1111-1111-111111111111",
                            project_id="22222222-2222-2222-2222-222222222222",
                            loop_id="33333333-3333-3333-3333-333333333333",
                            source_commit_id="44444444-4444-4444-4444-444444444444",
                            job_type=pb.TRAIN_DETECTION,
                            plugin_id="demo_det_v1",
                            mode=pb.ACTIVE_LEARNING,
                            query_strategy="uncertainty_1_minus_max_conf",
                            params=Struct(),
                            resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                        ),
                    )
                )
            )

        asyncio.create_task(_enqueue_assign())

    async def fake_heartbeat(*, executor_id: str, busy: bool, current_job_id: str | None, resources: dict[str, Any]) -> None:
        heartbeats.append((executor_id, busy, current_job_id or ""))

    async def fake_mark_idle(*, executor_id: str, job_id: str | None = None) -> None:
        mark_idle_records.append((executor_id, job_id))

    async def fake_unregister(executor_id: str) -> None:
        unregister_records.append(executor_id)

    async def fake_handle_ack(*, ack_for: str, status: int, message: str | None = None) -> None:
        ack_records.append((ack_for, status, message))

    monkeypatch.setattr(service, "_persist_job_event", fake_persist_event)
    monkeypatch.setattr(service, "_persist_job_result", fake_persist_result)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "mark_executor_idle", fake_mark_idle)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "unregister", fake_unregister)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "handle_ack", fake_handle_ack)

    server = grpc.aio.server()
    pb_grpc.add_RuntimeControlServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        client = _StreamClient(target=f"127.0.0.1:{port}", token=settings.INTERNAL_TOKEN)

        await client.send(
            pb.RuntimeMessage(
                register=pb.Register(
                    request_id="register-req-1",
                    executor_id="executor-e2e-1",
                    version="0.1.0",
                    plugins=[
                        pb.PluginCapability(
                            plugin_id="demo_det_v1",
                            version="0.1.0",
                            supported_job_types=["train_detection"],
                            supported_strategies=["uncertainty_1_minus_max_conf"],
                        )
                    ],
                    resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                )
            )
        )

        first = await client.recv()
        assert first.WhichOneof("payload") == "ack"
        assert first.ack.message == "registered"
        assert first.ack.status == pb.OK

        second = await client.recv()
        assert second.WhichOneof("payload") == "assign_job"
        assert second.assign_job.job.job_id == "11111111-1111-1111-1111-111111111111"

        await client.send(
            pb.RuntimeMessage(
                ack=pb.Ack(
                    request_id="ack-req-1",
                    ack_for="assign-req-1",
                    status=pb.OK,
                    message="accepted",
                )
            )
        )
        await client.send(
            pb.RuntimeMessage(
                heartbeat=pb.Heartbeat(
                    request_id="hb-1",
                    executor_id="executor-e2e-1",
                    busy=True,
                    current_job_id="11111111-1111-1111-1111-111111111111",
                    resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                )
            )
        )
        await client.send(
            pb.RuntimeMessage(
                job_event=pb.JobEvent(
                    request_id="evt-1",
                    job_id="11111111-1111-1111-1111-111111111111",
                    seq=1,
                    ts=1,
                    status_event=pb.StatusEvent(status=pb.RUNNING, reason="running"),
                )
            )
        )
        await client.send(
            pb.RuntimeMessage(
                job_result=pb.JobResult(
                    request_id="result-1",
                    job_id="11111111-1111-1111-1111-111111111111",
                    status=pb.SUCCEEDED,
                    metrics={"loss": 0.1},
                    artifacts=[
                        pb.ArtifactItem(
                            kind="weights",
                            name="best.pt",
                            uri="s3://bucket/path/best.pt",
                            meta=Struct(),
                        )
                    ],
                    candidates=[
                        pb.QueryCandidate(
                            sample_id="55555555-5555-5555-5555-555555555555",
                            score=0.9,
                            reason=Struct(),
                        )
                    ],
                )
            )
        )
        await asyncio.sleep(0.2)
        await client.close()
        await asyncio.sleep(0.1)

        assert len(ack_records) == 1
        assert ack_records[0][0] == "assign-req-1"
        assert len(heartbeats) == 1
        assert len(persisted_events) == 1
        assert len(persisted_results) == 1
        assert mark_idle_records == [("executor-e2e-1", "11111111-1111-1111-1111-111111111111")]
        assert unregister_records == ["executor-e2e-1"]
    finally:
        await server.stop(grace=0)


@pytest.mark.anyio
async def test_runtime_stream_rejects_invalid_token():
    service = RuntimeControlService()
    server = grpc.aio.server()
    pb_grpc.add_RuntimeControlServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        client = _StreamClient(target=f"127.0.0.1:{port}", token="bad-token")
        await client.send(
            pb.RuntimeMessage(
                register=pb.Register(
                    request_id="register-req-1",
                    executor_id="executor-e2e-2",
                    version="0.1.0",
                )
            )
        )
        with pytest.raises(grpc.aio.AioRpcError) as exc:
            await client.recv(timeout=2.0)
        assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED
        await client.close()
    finally:
        await server.stop(grace=0)


@pytest.mark.anyio
async def test_runtime_stream_allowlist_reject(monkeypatch):
    service = RuntimeControlService()

    async def fake_register(**kwargs):
        raise PermissionError("executor is not in allowlist")

    async def fake_unregister(executor_id: str) -> None:
        return

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "unregister", fake_unregister)

    server = grpc.aio.server()
    pb_grpc.add_RuntimeControlServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        client = _StreamClient(target=f"127.0.0.1:{port}", token=settings.INTERNAL_TOKEN)
        await client.send(
            pb.RuntimeMessage(
                register=pb.Register(
                    request_id="register-req-allowlist",
                    executor_id="executor-not-allowed",
                    version="0.1.0",
                )
            )
        )
        response = await client.recv()
        assert response.WhichOneof("payload") == "error"
        assert response.error.code == "FORBIDDEN"
        await client.close()
    finally:
        await server.stop(grace=0)


@pytest.mark.anyio
async def test_runtime_stream_duplicate_request_id_keeps_stream_alive(monkeypatch):
    service = RuntimeControlService()
    heartbeat_calls: list[str] = []

    async def fake_register(
            *,
            executor_id: str,
            queue: asyncio.Queue[pb.RuntimeMessage],
            version: str,
            plugin_ids: set[str],
            resources: dict[str, Any],
    ) -> None:
        return

    async def fake_heartbeat(*, executor_id: str, busy: bool, current_job_id: str | None, resources: dict[str, Any]) -> None:
        heartbeat_calls.append(executor_id)

    async def fake_unregister(executor_id: str) -> None:
        return

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "unregister", fake_unregister)

    server = grpc.aio.server()
    pb_grpc.add_RuntimeControlServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        client = _StreamClient(target=f"127.0.0.1:{port}", token=settings.INTERNAL_TOKEN)
        await client.send(
            pb.RuntimeMessage(
                register=pb.Register(
                    request_id="register-dup-1",
                    executor_id="executor-dup-1",
                    version="0.1.0",
                )
            )
        )
        response = await client.recv()
        assert response.WhichOneof("payload") == "ack"

        duplicate_id = "hb-dup-1"
        await client.send(
            pb.RuntimeMessage(
                heartbeat=pb.Heartbeat(
                    request_id=duplicate_id,
                    executor_id="executor-dup-1",
                    busy=False,
                    current_job_id="",
                )
            )
        )
        await client.send(
            pb.RuntimeMessage(
                heartbeat=pb.Heartbeat(
                    request_id=duplicate_id,
                    executor_id="executor-dup-1",
                    busy=False,
                    current_job_id="",
                )
            )
        )
        await asyncio.sleep(0.1)
        await client.close()
        assert heartbeat_calls == ["executor-dup-1", "executor-dup-1"]
    finally:
        await server.stop(grace=0)
