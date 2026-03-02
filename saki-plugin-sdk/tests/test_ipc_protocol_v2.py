from __future__ import annotations

import pytest

from saki_plugin_sdk import StepRuntimeContext
from saki_plugin_sdk.ipc import protocol


def _context() -> StepRuntimeContext:
    return StepRuntimeContext(
        step_id="step-ipc",
        round_id="round-ipc",
        round_index=1,
        attempt=1,
        step_type="train",
        mode="active_learning",
        split_seed=1,
        train_seed=2,
        sampling_seed=3,
        resolved_device_backend="cpu",
    )


def test_parse_command_payload_accepts_v2_and_parses_context():
    envelope = protocol.WorkerCommandEnvelope(
        request_id="req-1",
        action="train",
        step_id="step-ipc",
    )
    raw = protocol.build_command_payload(envelope=envelope, payload={"x": 1}, context=_context())
    parsed_envelope, payload = protocol.parse_command_payload(raw)
    assert parsed_envelope.protocol_version == protocol.WORKER_PROTOCOL_VERSION
    context = protocol.parse_runtime_context(payload)
    assert context.step_id == "step-ipc"
    assert context.train_seed == 2


def test_parse_command_payload_rejects_non_v2():
    raw = {
        "envelope": {
            "request_id": "req-2",
            "action": "train",
            "step_id": "step-ipc",
            "protocol_version": 1,
        },
        "payload": {},
    }
    with pytest.raises(ValueError, match="unsupported protocol_version"):
        protocol.parse_command_payload(raw)
