from saki_api.grpc.runtime_control import _map_status, _normalize_obb_payload
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus


def test_runtime_status_mapping():
    assert _map_status(pb.CREATED) == TrainingJobStatus.PENDING
    assert _map_status(pb.RUNNING) == TrainingJobStatus.RUNNING
    assert _map_status(pb.SUCCEEDED) == TrainingJobStatus.SUCCESS
    assert _map_status(pb.FAILED) == TrainingJobStatus.FAILED
    assert _map_status(pb.STOPPED) == TrainingJobStatus.CANCELLED


def test_runtime_obb_payload_accepts_normalized_contract():
    payload = _normalize_obb_payload(
        {"cx": 0.5, "cy": 0.5, "w": 0.25, "h": 0.25, "angle_deg": 15, "normalized": True}
    )
    assert payload["normalized"] is True
    assert abs(payload["cx"] - 0.5) < 1e-6
    assert abs(payload["cy"] - 0.5) < 1e-6
    assert abs(payload["w"] - 0.25) < 1e-6
    assert abs(payload["h"] - 0.25) < 1e-6
    assert abs(payload["angle_deg"] - 15.0) < 1e-6


def test_runtime_obb_payload_rejects_legacy_schema():
    payload = _normalize_obb_payload(
        {"x": 256, "y": 128, "width": 128, "height": 64, "rotation": 15}
    )
    assert payload == {}
