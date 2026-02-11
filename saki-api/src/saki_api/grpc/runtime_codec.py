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
    pb.PARTIAL_FAILED: "partial_failed",
}

_TEXT_TO_STATUS: dict[str, int] = {value: key for key, value in _STATUS_TO_TEXT.items()}
_TEXT_TO_STATUS.update(
    {
        "pending": pb.QUEUED,
        "success": pb.SUCCEEDED,
        "cancelled": pb.STOPPED,
        "partial_failed": pb.PARTIAL_FAILED,
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

_ACCELERATOR_TYPE_TO_TEXT: dict[int, str] = {
    pb.CPU: "cpu",
    pb.CUDA: "cuda",
    pb.MPS: "mps",
}
_TEXT_TO_ACCELERATOR_TYPE: dict[str, int] = {value: key for key, value in _ACCELERATOR_TYPE_TO_TEXT.items()}

_ACK_TYPE_TO_TEXT: dict[int, str] = {
    pb.ACK_TYPE_REGISTER: "register",
    pb.ACK_TYPE_ASSIGN_JOB: "assign_job",
    pb.ACK_TYPE_STOP_JOB: "stop_job",
    pb.ACK_TYPE_REQUEST: "request",
}
_TEXT_TO_ACK_TYPE: dict[str, int] = {value: key for key, value in _ACK_TYPE_TO_TEXT.items()}

_ACK_REASON_TO_TEXT: dict[int, str] = {
    pb.ACK_REASON_REGISTERED: "registered",
    pb.ACK_REASON_ACCEPTED: "accepted",
    pb.ACK_REASON_EXECUTOR_BUSY: "executor_busy",
    pb.ACK_REASON_STOPPING: "stopping",
    pb.ACK_REASON_JOB_NOT_RUNNING: "job_not_running",
    pb.ACK_REASON_REJECTED: "rejected",
}
_TEXT_TO_ACK_REASON: dict[str, int] = {value: key for key, value in _ACK_REASON_TO_TEXT.items()}


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


def ack_type_to_text(ack_type: int) -> str:
    return _ACK_TYPE_TO_TEXT.get(int(ack_type), "request")


def text_to_ack_type(ack_type: str | None) -> int:
    return _TEXT_TO_ACK_TYPE.get((ack_type or "").strip().lower(), pb.ACK_TYPE_REQUEST)


def ack_reason_to_text(reason: int) -> str:
    return _ACK_REASON_TO_TEXT.get(int(reason), "rejected")


def text_to_ack_reason(reason: str | None) -> int:
    return _TEXT_TO_ACK_REASON.get((reason or "").strip().lower(), pb.ACK_REASON_REJECTED)


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


def accelerator_type_to_text(accelerator: int) -> str:
    return _ACCELERATOR_TYPE_TO_TEXT.get(int(accelerator), "")


def text_to_accelerator_type(accelerator: str | None) -> int:
    return _TEXT_TO_ACCELERATOR_TYPE.get((accelerator or "").strip().lower(), pb.ACCELERATOR_TYPE_UNSPECIFIED)


def resource_summary_to_dict(resources: pb.ResourceSummary) -> dict[str, Any]:
    accelerators: list[dict[str, Any]] = []
    for item in resources.accelerators:
        accelerator_type = accelerator_type_to_text(item.type)
        if not accelerator_type:
            continue
        accelerators.append(
            {
                "type": accelerator_type,
                "available": bool(item.available),
                "device_count": int(item.device_count),
                "device_ids": [str(v) for v in item.device_ids],
            }
        )
    if not accelerators:
        gpu_count = int(resources.gpu_count)
        gpu_ids = [int(item) for item in resources.gpu_device_ids]
        if gpu_count > 0:
            accelerators.append(
                {
                    "type": "cuda",
                    "available": True,
                    "device_count": gpu_count,
                    "device_ids": [str(item) for item in gpu_ids] or [str(idx) for idx in range(gpu_count)],
                }
            )
        accelerators.append(
            {
                "type": "cpu",
                "available": True,
                "device_count": 1,
                "device_ids": ["cpu"],
            }
        )

    return {
        "gpu_count": int(resources.gpu_count),
        "gpu_device_ids": [int(item) for item in resources.gpu_device_ids],
        "cpu_workers": int(resources.cpu_workers),
        "memory_mb": int(resources.memory_mb),
        "accelerators": accelerators,
    }


def dict_to_resource_summary(resources: Mapping[str, Any] | None) -> pb.ResourceSummary:
    payload = resources or {}
    gpu_ids = payload.get("gpu_device_ids") or []
    accelerators_payload = payload.get("accelerators") or []

    accelerators: list[pb.AcceleratorCapability] = []
    if isinstance(accelerators_payload, list):
        for item in accelerators_payload:
            if not isinstance(item, Mapping):
                continue
            accelerator_type = text_to_accelerator_type(str(item.get("type") or ""))
            if accelerator_type == pb.ACCELERATOR_TYPE_UNSPECIFIED:
                continue
            device_ids_raw = item.get("device_ids") or []
            device_ids = [str(v) for v in device_ids_raw if str(v)]
            device_count = int(item.get("device_count") or (len(device_ids) if device_ids else 0))
            accelerators.append(
                pb.AcceleratorCapability(
                    type=accelerator_type,
                    available=bool(item.get("available")),
                    device_count=device_count,
                    device_ids=device_ids,
                )
            )

    gpu_count = int(payload.get("gpu_count") or 0)
    if not accelerators:
        if gpu_count > 0:
            accelerators.append(
                pb.AcceleratorCapability(
                    type=pb.CUDA,
                    available=True,
                    device_count=gpu_count,
                    device_ids=[str(item) for item in gpu_ids] or [str(idx) for idx in range(gpu_count)],
                )
            )
        accelerators.append(
            pb.AcceleratorCapability(
                type=pb.CPU,
                available=True,
                device_count=1,
                device_ids=["cpu"],
            )
        )

    return pb.ResourceSummary(
        gpu_count=gpu_count,
        gpu_device_ids=[int(item) for item in gpu_ids],
        cpu_workers=int(payload.get("cpu_workers") or 0),
        memory_mb=int(payload.get("memory_mb") or 0),
        accelerators=accelerators,
    )


def build_ack_message(
        *,
        ack_for: str,
        status: int,
        ack_type: int | str,
        ack_reason: int | str,
        detail: str = "",
        request_id: str | None = None,
) -> pb.RuntimeMessage:
    ack_type_value = ack_type if isinstance(ack_type, int) else text_to_ack_type(ack_type)
    ack_reason_value = ack_reason if isinstance(ack_reason, int) else text_to_ack_reason(ack_reason)
    return pb.RuntimeMessage(
        ack=pb.Ack(
            request_id=request_id or str(uuid.uuid4()),
            ack_for=ack_for,
            status=status,
            type=int(ack_type_value),
            reason=int(ack_reason_value),
            detail=detail,
        )
    )


def build_error_message(
        *,
        code: str,
        message: str,
        reply_to: str = "",
        ack_for: str = "",
        job_id: str = "",
        query_type: int | str | None = None,
        reason: str = "",
        request_id: str | None = None,
) -> pb.RuntimeMessage:
    query_type_value = pb.RUNTIME_QUERY_TYPE_UNSPECIFIED
    if isinstance(query_type, int):
        query_type_value = query_type
    elif isinstance(query_type, str):
        query_type_value = text_to_query_type(query_type)
    return pb.RuntimeMessage(
        error=pb.Error(
            request_id=request_id or str(uuid.uuid4()),
            code=code,
            message=message,
            reply_to=reply_to,
            ack_for=ack_for,
            job_id=job_id,
            query_type=query_type_value,
            reason=reason,
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
