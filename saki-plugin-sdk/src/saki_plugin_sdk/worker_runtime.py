from __future__ import annotations

import io
import struct
from collections.abc import Callable

from saki_plugin_sdk.gen.worker.v1 import worker_pb2

FRAME_EXECUTE_REQUEST = 1
FRAME_WORKER_EVENT = 2
FRAME_EXECUTE_RESULT = 3


def write_framed_message(stream: io.BufferedIOBase | io.BytesIO, kind: int, payload: bytes) -> None:
    frame = bytes([kind]) + payload
    stream.write(struct.pack(">I", len(frame)))
    stream.write(frame)


def read_framed_message(stream: io.BufferedIOBase | io.BytesIO) -> tuple[int, bytes]:
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError("missing frame header")

    size = struct.unpack(">I", header)[0]
    frame = stream.read(size)
    if len(frame) != size:
        raise EOFError("short frame payload")
    if not frame:
        raise EOFError("empty frame payload")

    return frame[0], frame[1:]


def run_worker_session(
    stdin: io.BufferedIOBase | io.BytesIO,
    stdout: io.BufferedIOBase | io.BytesIO,
    handler: Callable[[worker_pb2.ExecuteRequest, Callable[[str, bytes], None]], bytes],
) -> None:
    kind, payload = read_framed_message(stdin)
    if kind != FRAME_EXECUTE_REQUEST:
        raise ValueError(f"unexpected frame kind: {kind}")

    request = worker_pb2.ExecuteRequest()
    request.ParseFromString(payload)

    def emit(event_type: str, event_payload: bytes) -> None:
        event = worker_pb2.WorkerEvent(
            request_id=request.request_id,
            task_id=request.task_id,
            event_type=event_type,
            payload=event_payload,
        )
        write_framed_message(stdout, FRAME_WORKER_EVENT, event.SerializeToString())

    try:
        result_payload = handler(request, emit)
        result = worker_pb2.ExecuteResult(
            request_id=request.request_id,
            ok=True,
            payload=result_payload or b"",
        )
    except Exception as exc:  # pragma: no cover
        result = worker_pb2.ExecuteResult(
            request_id=request.request_id,
            ok=False,
            error_code="worker_error",
            error_message=str(exc),
        )

    write_framed_message(stdout, FRAME_EXECUTE_RESULT, result.SerializeToString())
