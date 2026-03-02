from pathlib import Path

import pytest

from saki_plugin_sdk import TrainArtifact, TrainOutput
from saki_plugin_sdk.ipc import protocol


def test_event_frames_roundtrip_json_payload():
    envelope = protocol.WorkerEventEnvelope(
        event_type="progress",
        step_id="step-1",
        ts=123,
        request_id="req-1",
    )
    frames = protocol.build_event_frames(
        topic="progress",
        envelope=envelope,
        payload={"epoch": 1, "step": 1},
    )
    topic, parsed_envelope, payload = protocol.parse_event_frames(frames)
    assert topic == "progress"
    assert parsed_envelope.event_type == "progress"
    assert parsed_envelope.step_id == "step-1"
    assert payload == {"epoch": 1, "step": 1}


def test_event_frames_roundtrip_binary_payload():
    envelope = protocol.WorkerEventEnvelope(
        event_type="worker",
        step_id="step-2",
        ts=456,
        request_id="req-2",
    )
    frames = protocol.build_event_frames(
        topic="worker",
        envelope=envelope,
        payload_bytes=b"\x00\x01\x02",
    )
    topic, parsed_envelope, payload = protocol.parse_event_frames(frames)
    assert topic == "worker"
    assert parsed_envelope.request_id == "req-2"
    assert payload == b"\x00\x01\x02"


def test_parse_event_frames_rejects_invalid_frame_count():
    with pytest.raises(ValueError, match="frame count"):
        protocol.parse_event_frames([b"only-one"])


def test_train_output_codec_roundtrip():
    output = TrainOutput(
        metrics={"loss": 0.1},
        artifacts=[
            TrainArtifact(
                kind="weights",
                name="best.pt",
                path=Path("/tmp/best.pt"),
                content_type="application/octet-stream",
                meta={"size": 123},
                required=True,
            )
        ],
    )
    payload = protocol.train_output_to_dict(output)
    parsed = protocol.train_output_from_dict(payload)
    assert parsed.metrics == {"loss": 0.1}
    assert len(parsed.artifacts) == 1
    assert parsed.artifacts[0].name == "best.pt"


def test_worker_event_topics_cover_required_topics():
    assert set(protocol.WORKER_EVENT_TOPICS) >= {"progress", "log", "metric", "status", "artifact", "worker"}
