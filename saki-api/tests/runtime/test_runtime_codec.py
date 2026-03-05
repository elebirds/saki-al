from __future__ import annotations

from google.protobuf.struct_pb2 import Struct

from saki_api.infra.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb


def test_struct_roundtrip():
    payload = {"a": 1, "b": {"c": "x"}}
    struct = runtime_codec.dict_to_struct(payload)
    assert runtime_codec.struct_to_dict(struct) == payload


def test_decode_step_status_event():
    event = pb.TaskEvent(
        request_id="r1",
        task_id="t1",
        seq=1,
        ts=1,
        status_event=pb.StatusEvent(status=pb.RUNNING, reason="ok"),
    )
    event_type, payload, status_enum = runtime_codec.decode_step_event(event)
    assert event_type == "status"
    assert payload["status"] == "running"
    assert payload["reason"] == "ok"
    assert status_enum == pb.RUNNING


def test_build_assign_step_message_and_decode_fields():
    message = runtime_codec.build_assign_step_message(
        request_id="assign-1",
        payload={
            "step_id": "step-1",
            "round_id": "round-1",
            "loop_id": "loop-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "step_type": "train",
            "dispatch_kind": "orchestrator",
            "plugin_id": "yolo_det_v1",
            "mode": "manual",
            "query_strategy": "random_baseline",
            "resolved_params": {"epochs": 1},
            "resources": {"gpu_count": 0, "cpu_workers": 2, "memory_mb": 1024},
            "round_index": 2,
            "attempt": 1,
            "depends_on_step_ids": ["step-0"],
        },
    )
    assert message.WhichOneof("payload") == "assign_task"
    task_payload = message.assign_task.task
    assert task_payload.task_id == "step-1"
    assert task_payload.step_type == pb.TRAIN
    assert task_payload.dispatch_kind == pb.ORCHESTRATOR
    assert task_payload.mode == pb.MANUAL
    assert runtime_codec.struct_to_dict(task_payload.resolved_params) == {"epochs": 1}


def test_step_type_codec_keeps_only_active_runtime_types():
    assert runtime_codec.text_to_step_type("legacy_removed_step_a") == pb.CUSTOM
    assert runtime_codec.text_to_step_type("legacy_removed_step_b") == pb.CUSTOM
    assert runtime_codec.step_type_to_text(pb.RUNTIME_STEP_TYPE_UNSPECIFIED) == "custom"
    assert runtime_codec.text_to_step_type("custom") == pb.CUSTOM
    assert runtime_codec.step_type_to_text(pb.CUSTOM) == "custom"


def test_resource_summary_supports_accelerators_roundtrip():
    summary = runtime_codec.dict_to_resource_summary(
        {
            "gpu_count": 1,
            "gpu_device_ids": [0],
            "cpu_workers": 4,
            "memory_mb": 1024,
            "accelerators": [
                {"type": "cuda", "available": True, "device_count": 1, "device_ids": ["0"]},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        }
    )
    payload = runtime_codec.resource_summary_to_dict(summary)
    assert payload["gpu_count"] == 1
    assert any(item["type"] == "cuda" for item in payload["accelerators"])
    assert runtime_codec.text_to_accelerator_type("mps") == pb.MPS
    assert runtime_codec.accelerator_type_to_text(pb.CPU) == "cpu"


def test_decode_step_artifact_event():
    meta = Struct()
    meta.update({"size": 12})
    event = pb.TaskEvent(
        request_id="r2",
        task_id="t2",
        seq=2,
        ts=2,
        artifact_event=pb.ArtifactEvent(
            artifact=pb.ArtifactItem(
                kind="weights",
                name="best.pt",
                uri="s3://bucket/path/best.pt",
                meta=meta,
            )
        ),
    )
    event_type, payload, status_enum = runtime_codec.decode_step_event(event)
    assert event_type == "artifact"
    assert payload["name"] == "best.pt"
    assert payload["uri"].startswith("s3://")
    assert payload["meta"]["size"] == 12
    assert status_enum is None


def test_decode_step_log_event_with_structured_fields():
    message_args = Struct()
    message_args.update({"epoch": 3})
    meta = Struct()
    meta.update({"source": "worker_stdio", "stream": "stderr", "line_count": 2})
    event = pb.TaskEvent(
        request_id="r3",
        task_id="t3",
        seq=3,
        ts=3,
        log_event=pb.LogEvent(
            level="DEBUG",
            message="display",
            raw_message="raw",
            message_key="runtime.progress.update",
            message_args=message_args,
            meta=meta,
        ),
    )
    event_type, payload, status_enum = runtime_codec.decode_step_event(event)
    assert event_type == "log"
    assert status_enum is None
    assert payload["level"] == "DEBUG"
    assert payload["message"] == "display"
    assert payload["raw_message"] == "raw"
    assert payload["message_key"] == "runtime.progress.update"
    assert payload["message_args"]["epoch"] == 3
    assert payload["meta"]["source"] == "worker_stdio"
    assert payload["meta"]["line_count"] == 2
