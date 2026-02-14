from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.modules.runtime.service.application.control_plane_dto import (
    RuntimeHeartbeatDTO,
    RuntimePluginCapabilityDTO,
    RuntimeRegisterDTO,
)

_ACTIVATE_SAMPLES_ENUM = pb.ACTIVATE_SAMPLES

_STATUS_TO_TEXT: dict[int, str] = {
    pb.PENDING: "pending",
    pb.DISPATCHING: "dispatching",
    pb.RUNNING: "running",
    pb.RETRYING: "retrying",
    pb.SUCCEEDED: "succeeded",
    pb.FAILED: "failed",
    pb.CANCELLED: "cancelled",
    pb.SKIPPED: "skipped",
}

_TEXT_TO_STATUS: dict[str, int] = {value: key for key, value in _STATUS_TO_TEXT.items()}

_STEP_TYPE_TO_TEXT: dict[int, str] = {
    pb.TRAIN: "train",
    pb.SCORE: "score",
    pb.SELECT: "select",
    _ACTIVATE_SAMPLES_ENUM: "activate_samples",
    pb.WAIT_ANNOTATION: "wait_annotation",
    pb.ADVANCE_BRANCH: "advance_branch",
    pb.EVAL: "eval",
    pb.EXPORT: "export",
    pb.UPLOAD_ARTIFACT: "upload_artifact",
    pb.CUSTOM: "custom",
}
_TEXT_TO_STEP_TYPE: dict[str, int] = {value: key for key, value in _STEP_TYPE_TO_TEXT.items()}

_DISPATCH_KIND_TO_TEXT: dict[int, str] = {
    pb.DISPATCHABLE: "dispatchable",
    pb.ORCHESTRATOR: "orchestrator",
}
_TEXT_TO_DISPATCH_KIND: dict[str, int] = {value: key for key, value in _DISPATCH_KIND_TO_TEXT.items()}

_LOOP_MODE_TO_TEXT: dict[int, str] = {
    pb.ACTIVE_LEARNING: "active_learning",
    pb.SIMULATION: "simulation",
    pb.MANUAL: "manual",
}
_TEXT_TO_LOOP_MODE: dict[str, int] = {value: key for key, value in _LOOP_MODE_TO_TEXT.items()}

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
    pb.ACK_TYPE_ASSIGN_STEP: "assign_step",
    pb.ACK_TYPE_STOP_STEP: "stop_step",
    pb.ACK_TYPE_REQUEST: "request",
}
_TEXT_TO_ACK_TYPE: dict[str, int] = {value: key for key, value in _ACK_TYPE_TO_TEXT.items()}

_ACK_REASON_TO_TEXT: dict[int, str] = {
    pb.ACK_REASON_REGISTERED: "registered",
    pb.ACK_REASON_ACCEPTED: "accepted",
    pb.ACK_REASON_EXECUTOR_BUSY: "executor_busy",
    pb.ACK_REASON_STOPPING: "stopping",
    pb.ACK_REASON_STEP_NOT_RUNNING: "step_not_running",
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
    return _STATUS_TO_TEXT.get(status, "pending")


def text_to_status(status: str | None) -> int:
    return _TEXT_TO_STATUS.get((status or "").lower(), pb.PENDING)


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


def step_type_to_text(step_type: int) -> str:
    return _STEP_TYPE_TO_TEXT.get(int(step_type), "custom")


def text_to_step_type(step_type: str | None) -> int:
    return _TEXT_TO_STEP_TYPE.get((step_type or "").strip().lower(), pb.CUSTOM)


def dispatch_kind_to_text(dispatch_kind: int) -> str:
    return _DISPATCH_KIND_TO_TEXT.get(int(dispatch_kind), "dispatchable")


def text_to_dispatch_kind(dispatch_kind: str | None) -> int:
    return _TEXT_TO_DISPATCH_KIND.get((dispatch_kind or "").strip().lower(), pb.DISPATCHABLE)


def loop_mode_to_text(mode: int) -> str:
    return _LOOP_MODE_TO_TEXT.get(int(mode), "active_learning")


def text_to_loop_mode(mode: str | None) -> int:
    return _TEXT_TO_LOOP_MODE.get((mode or "").strip().lower(), pb.ACTIVE_LEARNING)


def query_type_to_text(query_type: int) -> str:
    return _QUERY_TYPE_TO_TEXT.get(int(query_type), "labels")


def text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").strip().lower(), pb.LABELS)


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
    request_id: str | None = None,
    reply_to: str = "",
    ack_for: str = "",
    step_id: str = "",
    query_type: int = pb.RUNTIME_QUERY_TYPE_UNSPECIFIED,
    reason: str = "",
) -> pb.RuntimeMessage:
    step_id_value = str(step_id)
    return pb.RuntimeMessage(
        error=pb.Error(
            request_id=request_id or str(uuid.uuid4()),
            code=str(code),
            message=str(message),
            reply_to=str(reply_to),
            ack_for=str(ack_for),
            step_id=step_id_value,
            query_type=int(query_type),
            reason=str(reason),
        )
    )


def build_assign_step_message(*, request_id: str, payload: Mapping[str, Any]) -> pb.RuntimeMessage:
    step_type = text_to_step_type(str(payload.get("step_type") or "custom"))
    dispatch_kind = text_to_dispatch_kind(str(payload.get("dispatch_kind") or "dispatchable"))
    loop_mode = text_to_loop_mode(str(payload.get("mode") or "active_learning"))
    step_id = str(payload.get("step_id") or "")
    round_id = str(payload.get("round_id") or "")
    depends_on_step_ids = [str(v) for v in (payload.get("depends_on_step_ids") or [])]
    input_commit_id = str(payload.get("input_commit_id") or "")
    return pb.RuntimeMessage(
        assign_step=pb.AssignStep(
            request_id=request_id,
            step=pb.StepPayload(
                step_id=step_id,
                round_id=round_id,
                loop_id=str(payload.get("loop_id") or ""),
                project_id=str(payload.get("project_id") or ""),
                input_commit_id=input_commit_id,
                step_type=step_type,
                dispatch_kind=dispatch_kind,
                plugin_id=str(payload.get("plugin_id") or ""),
                mode=loop_mode,
                query_strategy=str(payload.get("query_strategy") or ""),
                resolved_params=dict_to_struct(payload.get("resolved_params") or {}),
                resources=dict_to_resource_summary(payload.get("resources") or {}),
                round_index=int(payload.get("round_index") or 0),
                attempt=int(payload.get("attempt") or 1),
                depends_on_step_ids=depends_on_step_ids,
            ),
        )
    )


def build_stop_step_message(*, request_id: str, step_id: str, reason: str) -> pb.RuntimeMessage:
    step_id = str(step_id)
    return pb.RuntimeMessage(
        stop_step=pb.StopStep(
            request_id=request_id,
            step_id=step_id,
            reason=str(reason or ""),
        )
    )


def decode_step_event(event: pb.StepEvent) -> tuple[str, dict[str, Any], int | None]:
    payload_type = event.WhichOneof("event_payload")
    if payload_type == "status_event":
        status_value = int(event.status_event.status)
        return (
            "status",
            {
                "status": status_to_text(status_value),
                "reason": event.status_event.reason,
            },
            status_value,
        )
    if payload_type == "log_event":
        return (
            "log",
            {
                "level": event.log_event.level,
                "message": event.log_event.message,
            },
            None,
        )
    if payload_type == "progress_event":
        return (
            "progress",
            {
                "epoch": int(event.progress_event.epoch),
                "step": int(event.progress_event.step),
                "total_steps": int(event.progress_event.total_steps),
                "eta_sec": int(event.progress_event.eta_sec),
            },
            None,
        )
    if payload_type == "metric_event":
        return (
            "metric",
            {
                "step": int(event.metric_event.step),
                "epoch": int(event.metric_event.epoch),
                "metrics": {key: float(value) for key, value in event.metric_event.metrics.items()},
            },
            None,
        )
    if payload_type == "artifact_event":
        return (
            "artifact",
            {
                "kind": event.artifact_event.artifact.kind,
                "name": event.artifact_event.artifact.name,
                "uri": event.artifact_event.artifact.uri,
                "meta": struct_to_dict(event.artifact_event.artifact.meta),
            },
            None,
        )

    return (
        "log",
        {
            "level": "WARN",
            "message": "unknown runtime event payload",
        },
        None,
    )


def parse_register(message: pb.Register) -> RuntimeRegisterDTO:
    plugins: list[RuntimePluginCapabilityDTO] = []
    for item in message.plugins:
        plugins.append(
            RuntimePluginCapabilityDTO(
                plugin_id=str(item.plugin_id),
                version=str(item.version),
                supported_step_types=[str(v) for v in item.supported_step_types],
                supported_strategies=[str(v) for v in item.supported_strategies],
                display_name=str(item.display_name),
                request_config_schema=struct_to_dict(item.request_config_schema),
                default_request_config=struct_to_dict(item.default_request_config),
                supported_accelerators=[
                    accelerator_type_to_text(v)
                    for v in item.supported_accelerators
                    if accelerator_type_to_text(v)
                ],
                supports_auto_fallback=bool(item.supports_auto_fallback),
            )
        )
    return RuntimeRegisterDTO(
        request_id=str(message.request_id),
        executor_id=str(message.executor_id),
        version=str(message.version),
        plugins=plugins,
        resources=resource_summary_to_dict(message.resources),
    )


def parse_heartbeat(message: pb.Heartbeat) -> RuntimeHeartbeatDTO:
    return RuntimeHeartbeatDTO(
        request_id=str(message.request_id),
        executor_id=str(message.executor_id),
        busy=bool(message.busy),
        current_step_id=str(message.current_step_id or ""),
        resources=resource_summary_to_dict(message.resources),
    )
