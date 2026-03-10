from __future__ import annotations

import asyncio

import pytest

from saki_executor.plugins.ipc.client import PluginWorkerClient


class _FakeReqSocket:
    def __init__(self) -> None:
        self.recv_started = asyncio.Event()
        self.closed = False

    async def send_json(self, payload) -> None:
        del payload

    async def recv_json(self):
        self.recv_started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    def close(self, linger=0) -> None:
        del linger
        self.closed = True


class _FakeSubSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self, linger=0) -> None:
        del linger
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0


@pytest.mark.anyio
async def test_terminate_cancels_pending_worker_request(monkeypatch):
    sent_signals: list[int] = []

    monkeypatch.setattr("os.getpgid", lambda pid: pid)

    def _fake_killpg(pid: int, sig: int) -> None:
        del pid
        sent_signals.append(int(sig))

    monkeypatch.setattr("os.killpg", _fake_killpg)

    client = PluginWorkerClient(
        plugin_id="demo",
        task_id="task-1",
        event_handler=lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    client._started = True  # noqa: SLF001
    client._closed = False  # noqa: SLF001
    client._req_socket = _FakeReqSocket()  # noqa: SLF001
    client._sub_socket = _FakeSubSocket()  # noqa: SLF001
    client._process = _FakeProcess()  # noqa: SLF001

    request_task = asyncio.create_task(client.request(action="train", payload={}))
    await client._req_socket.recv_started.wait()  # noqa: SLF001

    await client.terminate()

    assert request_task.done() is True
    assert request_task.cancelled() is True
    assert client._req_socket is None  # noqa: SLF001
    assert client._sub_socket is None  # noqa: SLF001
    assert sent_signals
