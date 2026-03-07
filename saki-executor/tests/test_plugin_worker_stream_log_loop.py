from __future__ import annotations

import asyncio
from typing import Any

import pytest

from saki_executor.plugins.ipc.client import PluginWorkerClient


@pytest.mark.anyio
async def test_stream_log_loop_handles_long_stdout_chunk_without_newline():
    events: list[tuple[str, dict[str, Any]]] = []

    async def on_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    client = PluginWorkerClient(
        plugin_id="demo_det_v1",
        task_id="task-stream-long-line",
        event_handler=on_event,
        entrypoint_module="demo.entrypoint",
    )
    reader = asyncio.StreamReader()
    reader.feed_data(("x" * 400_000).encode("utf-8"))
    reader.feed_eof()

    await client._stream_log_loop(reader, "stdout")

    assert len(events) >= 1
    assert all(item[0] == "log" for item in events)


@pytest.mark.anyio
async def test_stream_log_loop_splits_carriage_return_progress_lines():
    events: list[tuple[str, dict[str, Any]]] = []

    async def on_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    client = PluginWorkerClient(
        plugin_id="demo_det_v1",
        task_id="task-stream-cr",
        event_handler=on_event,
        entrypoint_module="demo.entrypoint",
    )
    reader = asyncio.StreamReader()
    reader.feed_data(b"progress=10%\rprogress=50%\rprogress=100%\n")
    reader.feed_eof()

    await client._stream_log_loop(reader, "stdout")

    messages = [str(payload.get("message") or "") for _, payload in events]
    assert any("progress=10%" in msg for msg in messages)
    assert any("progress=50%" in msg for msg in messages)
    assert any("progress=100%" in msg for msg in messages)


@pytest.mark.anyio
async def test_stream_log_loop_handles_mixed_newline_and_carriage_return():
    events: list[tuple[str, dict[str, Any]]] = []

    async def on_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    client = PluginWorkerClient(
        plugin_id="demo_det_v1",
        task_id="task-stream-mixed",
        event_handler=on_event,
        entrypoint_module="demo.entrypoint",
    )
    reader = asyncio.StreamReader()
    reader.feed_data(b"line-a\nline-b\rline-c\n")
    reader.feed_eof()

    await client._stream_log_loop(reader, "stdout")

    messages = [str(payload.get("message") or "") for _, payload in events]
    assert any("line-a" in msg for msg in messages)
    assert any("line-b" in msg for msg in messages)
    assert any("line-c" in msg for msg in messages)
