from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from saki_executor.steps.orchestration.event_emitter import StepEventEmitter
from saki_plugin_sdk import StepReporter


@pytest.mark.anyio
async def test_stage_events_use_structured_step_stage_key(tmp_path: Path):
    events_path = tmp_path / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    reporter = StepReporter("step-stage-1", events_path)
    captured: list[dict] = []

    async def _push(event: dict) -> None:
        captured.append(event)

    emitter = StepEventEmitter(
        reporter=reporter,
        stop_event=asyncio.Event(),
        push_event=_push,
    )

    await emitter.emit_stage_start(stage="syncing_env", message="start sync")
    await emitter.emit_stage_success(stage="syncing_env", message="sync done")
    await emitter.emit_stage_fail(stage="syncing_env", error_code="ENV_SYNC_FAILED", message="sync fail")

    assert len(captured) == 3
    assert captured[0]["payload"]["message_key"] == "step.stage"
    assert captured[0]["payload"]["message_args"] == {"stage": "syncing_env", "phase": "start"}
    assert captured[1]["payload"]["message_args"] == {"stage": "syncing_env", "phase": "success"}
    assert captured[2]["payload"]["message_args"] == {
        "stage": "syncing_env",
        "phase": "fail",
        "error_code": "ENV_SYNC_FAILED",
    }
    assert captured[2]["payload"]["message"].startswith("[ENV_SYNC_FAILED]")
