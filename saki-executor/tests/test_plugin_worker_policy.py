"""Test that tasks for unknown plugins fail gracefully."""

import asyncio
from pathlib import Path

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.steps.manager import StepManager


def _build_manager(tmp_path: Path) -> StepManager:
    registry = PluginRegistry()
    # intentionally empty — no plugins registered
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    return StepManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)


@pytest.mark.anyio
async def test_unregistered_plugin_fails(tmp_path: Path):
    manager = _build_manager(tmp_path)
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage):
        raise AssertionError(f"unexpected request: {message.WhichOneof('payload')}")

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-unknown-1",
        {
            "step_id": "task-unknown-1",
            "round_id": "job-unknown-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": "non_existent_plugin",
            "mode": "simulation",
            "step_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "random_baseline",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=1.0)  # noqa: SLF001

    result_messages = [item for item in sent_messages if item.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    result = result_messages[0].step_result
    assert result.status == pb.FAILED
    assert "not found" in result.error_message.lower() or "not loadable" in result.error_message.lower()
