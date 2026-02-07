from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_api.grpc_gen import runtime_control_pb2 as pb


_STATUS_TO_TEXT: dict[int, str] = {
    pb.CREATED: "created",
    pb.QUEUED: "queued",
    pb.RUNNING: "running",
    pb.STOPPING: "stopping",
    pb.STOPPED: "stopped",
    pb.SUCCEEDED: "succeeded",
    pb.FAILED: "failed",
}

_TEXT_TO_STATUS: dict[str, int] = {value: key for key, value in _STATUS_TO_TEXT.items()}
_TEXT_TO_STATUS.update(
    {
        "pending": pb.QUEUED,
        "success": pb.SUCCEEDED,
        "cancelled": pb.STOPPED,
    }
)

_JOB_TYPE_TO_TEXT: dict[int, str] = {
    pb.TRAIN_DETECTION: "train_detection",
}
_TEXT_TO_JOB_TYPE: dict[str, int] = {value: key for key, value in _JOB_TYPE_TO_TEXT.items()}

_JOB_MODE_TO_TEXT: dict[int, str] = {
    pb.ACTIVE_LEARNING: "active_learning",
    pb.SIMULATION: "simulation",
}
_TEXT_TO_JOB_MODE: dict[str, int] = {value: key for key, value in _JOB_MODE_TO_TEXT.items()}

_QUERY_TYPE_TO_TEXT: dict[int, str] = {
    pb.LABELS: "labels",
    pb.SAMPLES: "samples",
    pb.ANNOTATIONS: "annotations",
    pb.UNLABELED_SAMPLES: "unlabeled_samples",
}
_TEXT_TO_QUERY_TYPE: dict[str, int] = {value: key for key, value in _QUERY_TYPE_TO_TEXT.items()}


def dict_to_struct(payload: Mapping[str, Any] | None) -> Struct:
    struct = Struct()
    if payload:
        struct.update(dict(payload))
    return struct


def struct_to_dict(payload: Struct | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not payload.ListFields():
        return {}
    return dict(MessageToDict(payload, preserving_proto_field_name=True))


def status_to_text(status: int) -> str:
    return _STATUS_TO_TEXT.get(status, "queued")


def text_to_status(status: str | None) -> int:
    return _TEXT_TO_STATUS.get((status or "").lower(), pb.QUEUED)


def ack_status_to_text(status: int) -> str:
    return "ok" if status == pb.OK else "error"


def text_to_ack_status(status: str | None) -> int:
    return pb.OK if (status or "").lower() == "ok" else pb.ERROR


def job_type_to_text(job_type: int) -> str:
    return _JOB_TYPE_TO_TEXT.get(int(job_type), "train_detection")


def text_to_job_type(job_type: str | None) -> int:
    return _TEXT_TO_JOB_TYPE.get((job_type or "").lower(), pb.TRAIN_DETECTION)


def job_mode_to_text(mode: int) -> str:
    return _JOB_MODE_TO_TEXT.get(int(mode), "active_learning")


def text_to_job_mode(mode: str | None) -> int:
    return _TEXT_TO_JOB_MODE.get((mode or "").lower(), pb.ACTIVE_LEARNING)


def query_type_to_text(query_type: int) -> str:
    return _QUERY_TYPE_TO_TEXT.get(int(query_type), "labels")


def text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").lower(), pb.LABELS)


def resource_summary_to_dict(resources: pb.ResourceSummary) -> dict[str, Any]:
    return {
        "gpu_count": int(resources.gpu_count),
        "gpu_device_ids": [int(item) for item in resources.gpu_device_ids],
        "cpu_workers": int(resources.cpu_workers),
        "memory_mb": int(resources.memory_mb),
    }


def dict_to_resource_summary(resources: Mapping[str, Any] | None) -> pb.ResourceSummary:
    payload = resources or {}
    gpu_ids = payload.get("gpu_device_ids") or []
    return pb.ResourceSummary(
        gpu_count=int(payload.get("gpu_count") or 0),
        gpu_device_ids=[int(item) for item in gpu_ids],
        cpu_workers=int(payload.get("cpu_workers") or 0),
        memory_mb=int(payload.get("memory_mb") or 0),
    )


def build_ack_message(
        *,
        ack_for: str,
        status: int,
        message: str,
        request_id: str | None = None,
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        ack=pb.Ack(
            request_id=request_id or str(uuid.uuid4()),
            ack_for=ack_for,
            status=status,
            message=message,
        )
    )


def build_error_message(
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        request_id: str | None = None,
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        error=pb.Error(
            request_id=request_id or str(uuid.uuid4()),
            code=code,
            message=message,
            details=dict_to_struct(details),
        )
    )


def decode_job_event(event: pb.JobEvent) -> tuple[str, dict[str, Any], int | None]:
    payload_type = event.WhichOneof("event_payload")
    if payload_type == "status_event":
        status_value = int(event.status_event.status)
        payload: dict[str, Any] = {"status": status_to_text(status_value)}
        if event.status_event.reason:
            payload["reason"] = event.status_event.reason
        return "status", payload, status_value

    if payload_type == "log_event":
        return "log", {"level": event.log_event.level, "message": event.log_event.message}, None

    if payload_type == "progress_event":
        payload = {
            "epoch": int(event.progress_event.epoch),
            "step": int(event.progress_event.step),
            "total_steps": int(event.progress_event.total_steps),
            "eta_sec": int(event.progress_event.eta_sec),
        }
        return "progress", payload, None

    if payload_type == "metric_event":
        payload = {
            "step": int(event.metric_event.step),
            "epoch": int(event.metric_event.epoch),
            "metrics": {str(k): float(v) for k, v in event.metric_event.metrics.items()},
        }
        return "metric", payload, None

    if payload_type == "artifact_event":
        artifact = event.artifact_event.artifact
        payload = {
            "kind": artifact.kind,
            "name": artifact.name,
            "uri": artifact.uri,
            "meta": struct_to_dict(artifact.meta),
        }
        return "artifact", payload, None

    return "log", {"level": "WARN", "message": "unknown event payload"}, None
