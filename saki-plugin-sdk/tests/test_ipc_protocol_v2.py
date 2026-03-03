from __future__ import annotations

import pytest

from saki_plugin_sdk import (
    DeviceBinding,
    ExecutionBindingContext,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    StepRuntimeContext,
)
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


def _execution_context() -> ExecutionBindingContext:
    return ExecutionBindingContext(
        step_context=_context(),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 8192,
                "gpus": [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        ),
        runtime_capability=RuntimeCapabilitySnapshot(
            framework="torch",
            framework_version="2.2.0",
            backends=["cpu"],
            backend_details={},
            errors=[],
        ),
        device_binding=DeviceBinding(
            backend="cpu",
            device_spec="cpu",
            precision="fp32",
            profile_id="cpu",
            reason="test",
            fallback_applied=False,
        ),
        profile_id="cpu",
    )


def test_parse_command_payload_accepts_v3_and_parses_context():
    envelope = protocol.WorkerCommandEnvelope(
        request_id="req-1",
        action="train",
        step_id="step-ipc",
    )
    raw = protocol.build_command_payload(
        envelope=envelope,
        payload={"x": 1},
        runtime_context=_context(),
        execution_binding_context=_execution_context(),
    )
    parsed_envelope, payload = protocol.parse_command_payload(raw)
    assert parsed_envelope.protocol_version == protocol.WORKER_PROTOCOL_VERSION
    context = protocol.parse_runtime_context(payload)
    assert context.step_id == "step-ipc"
    assert context.train_seed == 2
    execution_context = protocol.parse_execution_binding_context(payload)
    assert execution_context.device_binding.backend == "cpu"


def test_parse_command_payload_rejects_non_v3():
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


def test_parse_command_payload_requires_protocol_version():
    raw = {
        "envelope": {
            "request_id": "req-3",
            "action": "train",
            "step_id": "step-ipc",
        },
        "payload": {},
    }
    with pytest.raises(ValueError, match="missing protocol_version"):
        protocol.parse_command_payload(raw)
