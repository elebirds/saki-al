from saki_api.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb


def test_struct_roundtrip():
    payload = {"a": 1, "b": {"c": "x"}}
    struct = runtime_codec.dict_to_struct(payload)
    assert runtime_codec.struct_to_dict(struct) == payload


def test_decode_status_event():
    event = pb.JobEvent(
        request_id="r1",
        job_id="j1",
        seq=1,
        ts=1,
        status_event=pb.StatusEvent(status=pb.RUNNING, reason="ok"),
    )
    event_type, payload, status_enum = runtime_codec.decode_job_event(event)
    assert event_type == "status"
    assert payload["status"] == "running"
    assert payload["reason"] == "ok"
    assert status_enum == pb.RUNNING


def test_query_job_mode_type_mapping():
    assert runtime_codec.text_to_query_type("labels") == pb.LABELS
    assert runtime_codec.query_type_to_text(pb.UNLABELED_SAMPLES) == "unlabeled_samples"

    assert runtime_codec.text_to_job_type("train_detection") == pb.TRAIN_DETECTION
    assert runtime_codec.job_type_to_text(pb.TRAIN_DETECTION) == "train_detection"

    assert runtime_codec.text_to_job_mode("active_learning") == pb.ACTIVE_LEARNING
    assert runtime_codec.job_mode_to_text(pb.SIMULATION) == "simulation"
