from __future__ import annotations

from io import BytesIO

from saki_plugin_sdk.gen.worker.v1 import worker_pb2
from saki_plugin_sdk.worker_runtime import (
    FRAME_EXECUTE_REQUEST,
    FRAME_EXECUTE_RESULT,
    FRAME_WORKER_EVENT,
    read_framed_message,
    run_worker_session,
    write_framed_message,
)


def test_execute_request_to_execute_result_flow():
    stdin = BytesIO()
    stdout = BytesIO()

    request = worker_pb2.ExecuteRequest(
        request_id="req-1",
        task_id="task-1",
        action="train",
        payload=b'{"epochs":1}',
    )
    write_framed_message(stdin, FRAME_EXECUTE_REQUEST, request.SerializeToString())
    stdin.seek(0)

    def handler(req: worker_pb2.ExecuteRequest, emit) -> bytes:
        emit("progress", b'{"percent":42}')
        return b'{"artifact":"best.pt"}'

    run_worker_session(stdin, stdout, handler)
    stdout.seek(0)

    kind, payload = read_framed_message(stdout)
    assert kind == FRAME_WORKER_EVENT
    event = worker_pb2.WorkerEvent()
    event.ParseFromString(payload)
    assert event.request_id == "req-1"
    assert event.event_type == "progress"

    kind, payload = read_framed_message(stdout)
    assert kind == FRAME_EXECUTE_RESULT
    result = worker_pb2.ExecuteResult()
    result.ParseFromString(payload)
    assert result.request_id == "req-1"
    assert result.ok is True
    assert result.payload == b'{"artifact":"best.pt"}'
