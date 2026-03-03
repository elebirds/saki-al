from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from saki_executor.commands.server import CommandServer
from saki_plugin_sdk import HostCapabilitySnapshot


class _StepManagerStub:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_host_capability(self) -> HostCapabilitySnapshot:
        self.refresh_calls += 1
        return HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 8192,
                "gpus": [],
                "metal_available": True,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        )


@pytest.mark.anyio
async def test_refresh_hw_command_triggers_manual_capability_refresh():
    step_manager = _StepManagerStub()
    server = CommandServer(
        step_manager=step_manager,  # type: ignore[arg-type]
        plugin_registry=SimpleNamespace(all=lambda: []),  # type: ignore[arg-type]
        client=SimpleNamespace(connect=lambda: None, disconnect=lambda force=False: force),  # type: ignore[arg-type]
        shutdown_event=asyncio.Event(),
    )

    await server.execute("refresh-hw")
    assert step_manager.refresh_calls == 1
