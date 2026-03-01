from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.steps.state import StepStatus

_STATUS_TO_ENUM: dict[str, int] = {
    StepStatus.PENDING.value: pb.PENDING,
    StepStatus.DISPATCHING.value: pb.DISPATCHING,
    StepStatus.RUNNING.value: pb.RUNNING,
    StepStatus.RETRYING.value: pb.RETRYING,
    StepStatus.SUCCEEDED.value: pb.SUCCEEDED,
    StepStatus.FAILED.value: pb.FAILED,
    StepStatus.CANCELLED.value: pb.CANCELLED,
    StepStatus.SKIPPED.value: pb.SKIPPED,
}

_ENUM_TO_STATUS: dict[int, str] = {
    pb.PENDING: StepStatus.PENDING.value,
    pb.DISPATCHING: StepStatus.DISPATCHING.value,
    pb.RUNNING: StepStatus.RUNNING.value,
    pb.RETRYING: StepStatus.RETRYING.value,
    pb.SUCCEEDED: StepStatus.SUCCEEDED.value,
    pb.FAILED: StepStatus.FAILED.value,
    pb.CANCELLED: StepStatus.CANCELLED.value,
    pb.SKIPPED: StepStatus.SKIPPED.value,
}

_STEP_TYPE_TO_TEXT: dict[int, str] = {
    pb.TRAIN: "train",
    pb.EVAL: "eval",
    pb.SCORE: "score",
    pb.SELECT: "select",
    pb.PREDICT: "predict",
    pb.CUSTOM: "custom",
}

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


def _resolve_step_id(step_id: str | None) -> str:
    value = str(step_id or "").strip()
    return value


def dict_to_struct(payload: Mapping[str, Any] | None) -> Struct:
    struct = Struct()
    if payload:
        struct.update(dict(payload))
    return struct


def struct_to_dict(payload: Struct | None) -> dict[str, Any]:
    if payload is None or not payload.ListFields():
        return {}
    return dict(MessageToDict(payload, preserving_proto_field_name=True))


def step_status_to_enum(status: str | StepStatus) -> int:
    raw = status.value if isinstance(status, StepStatus) else str(status or "").lower()
    return _STATUS_TO_ENUM.get(raw, pb.PENDING)


def status_enum_to_text(status: int) -> str:
    return _ENUM_TO_STATUS.get(int(status), StepStatus.PENDING.value)


def text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").lower(), pb.LABELS)


def dispatch_kind_to_text(dispatch_kind: int) -> str:
    return _DISPATCH_KIND_TO_TEXT.get(int(dispatch_kind), "dispatchable")


def text_to_dispatch_kind(dispatch_kind: str | None) -> int:
    return _TEXT_TO_DISPATCH_KIND.get((dispatch_kind or "").strip().lower(), pb.DISPATCHABLE)


def query_type_to_text(query_type: int) -> str:
    return _QUERY_TYPE_TO_TEXT.get(int(query_type), "labels")


def accelerator_type_to_text(accelerator: int) -> str:
    return _ACCELERATOR_TYPE_TO_TEXT.get(int(accelerator), "")


def text_to_accelerator_type(accelerator: str | None) -> int:
    return _TEXT_TO_ACCELERATOR_TYPE.get((accelerator or "").strip().lower(), pb.ACCELERATOR_TYPE_UNSPECIFIED)


def ack_type_to_text(ack_type: int) -> str:
    return _ACK_TYPE_TO_TEXT.get(int(ack_type), "request")


def text_to_ack_type(ack_type: str | None) -> int:
    return _TEXT_TO_ACK_TYPE.get((ack_type or "").strip().lower(), pb.ACK_TYPE_REQUEST)


def ack_reason_to_text(reason: int) -> str:
    return _ACK_REASON_TO_TEXT.get(int(reason), "rejected")


def text_to_ack_reason(reason: str | None) -> int:
    return _TEXT_TO_ACK_REASON.get((reason or "").strip().lower(), pb.ACK_REASON_REJECTED)


def _dict_to_resource_summary(resources: Mapping[str, Any] | None) -> pb.ResourceSummary:
    payload = resources or {}
    gpu_ids = [int(item) for item in (payload.get("gpu_device_ids") or [])]
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
        gpu_device_ids=gpu_ids,
        cpu_workers=int(payload.get("cpu_workers") or 0),
        memory_mb=int(payload.get("memory_mb") or 0),
        accelerators=accelerators,
    )


def _resource_summary_to_dict(resources: pb.ResourceSummary) -> dict[str, Any]:
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


def build_register_message(
    *,
    request_id: str,
    executor_id: str,
    version: str,
    plugins: list[dict[str, Any]],
    resources: Mapping[str, Any],
) -> pb.RuntimeMessage:
    plugin_caps: list[pb.PluginCapability] = []
    for item in plugins:
        plugin_caps.append(
            pb.PluginCapability(
                plugin_id=str(item.get("plugin_id") or ""),
                version=str(item.get("version") or ""),
                supported_step_types=[str(v) for v in (item.get("supported_step_types") or [])],
                supported_strategies=[str(v) for v in (item.get("supported_strategies") or [])],
                display_name=str(item.get("display_name") or item.get("plugin_id") or ""),
                request_config_schema=dict_to_struct(item.get("request_config_schema") or {}),
                default_request_config=dict_to_struct(item.get("default_request_config") or {}),
                supported_accelerators=[
                    text_to_accelerator_type(str(v))
                    for v in (item.get("supported_accelerators") or [])
                    if text_to_accelerator_type(str(v)) != pb.ACCELERATOR_TYPE_UNSPECIFIED
                ],
                supports_auto_fallback=bool(item.get("supports_auto_fallback", True)),
            )
        )

    return pb.RuntimeMessage(
        register=pb.Register(
            request_id=request_id,
            executor_id=executor_id,
            version=version,
            plugins=plugin_caps,
            resources=_dict_to_resource_summary(resources),
        )
    )


def build_heartbeat_message(
    *,
    request_id: str,
    executor_id: str,
    busy: bool,
    current_step_id: str | None,
    resources: Mapping[str, Any],
) -> pb.RuntimeMessage:
    step_id = str(current_step_id or "")
    return pb.RuntimeMessage(
        heartbeat=pb.Heartbeat(
            request_id=request_id,
            executor_id=executor_id,
            busy=busy,
            current_step_id=step_id,
            resources=_dict_to_resource_summary(resources),
        )
    )


def build_ack_message(
    *,
    request_id: str,
    ack_for: str,
    ok: bool,
    ack_type: str,
    ack_reason: str,
    detail: str = "",
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        ack=pb.Ack(
            request_id=request_id,
            ack_for=ack_for,
            status=pb.OK if ok else pb.ERROR,
            type=text_to_ack_type(ack_type),
            reason=text_to_ack_reason(ack_reason),
            detail=detail,
        )
    )


def build_data_request_message(
    *,
    request_id: str,
    step_id: str,
    query_type: str,
    project_id: str,
    commit_id: str,
    cursor: str | None,
    limit: int,
    preferred_chunk_bytes: int = 0,
    max_uncompressed_bytes: int = 0,
) -> pb.RuntimeMessage:
    step_id = str(step_id)
    return pb.RuntimeMessage(
        data_request=pb.DataRequest(
            request_id=request_id,
            step_id=step_id,
            query_type=text_to_query_type(query_type),
            project_id=project_id,
            commit_id=commit_id,
            cursor=str(cursor or ""),
            limit=int(limit),
            preferred_chunk_bytes=int(preferred_chunk_bytes),
            max_uncompressed_bytes=int(max_uncompressed_bytes),
        )
    )


def build_upload_ticket_request_message(
    *,
    request_id: str,
    step_id: str,
    artifact_name: str,
    content_type: str,
) -> pb.RuntimeMessage:
    step_id = str(step_id)
    return pb.RuntimeMessage(
        upload_ticket_request=pb.UploadTicketRequest(
            request_id=request_id,
            step_id=step_id,
            artifact_name=artifact_name,
            content_type=content_type,
        )
    )


def build_step_event_message(
    *,
    request_id: str,
    step_id: str,
    seq: int,
    ts: int,
    event_type: str,
    payload: Mapping[str, Any],
) -> pb.RuntimeMessage:
    step_id = str(step_id)
    step_event = pb.StepEvent(
        request_id=request_id,
        step_id=step_id,
        seq=int(seq),
        ts=int(ts),
    )

    if event_type == "status":
        step_event.status_event.status = step_status_to_enum(str(payload.get("status") or ""))
        if payload.get("reason") is not None:
            step_event.status_event.reason = str(payload.get("reason"))
    elif event_type == "log":
        step_event.log_event.level = str(payload.get("level") or "")
        step_event.log_event.message = str(payload.get("message") or "")
    elif event_type == "progress":
        step_event.progress_event.epoch = int(payload.get("epoch") or 0)
        step_event.progress_event.step = int(payload.get("step") or 0)
        step_event.progress_event.total_steps = int(payload.get("total_steps") or 0)
        step_event.progress_event.eta_sec = int(payload.get("eta_sec") or 0)
    elif event_type == "metric":
        step_event.metric_event.step = int(payload.get("step") or 0)
        step_event.metric_event.epoch = int(payload.get("epoch") or 0)
        for metric_name, metric_value in (payload.get("metrics") or {}).items():
            try:
                step_event.metric_event.metrics[str(metric_name)] = float(metric_value)
            except Exception:
                continue
    elif event_type == "artifact":
        artifact = step_event.artifact_event.artifact
        artifact.kind = str(payload.get("kind") or "artifact")
        artifact.name = str(payload.get("name") or "")
        artifact.uri = str(payload.get("uri") or "")
        artifact.meta.CopyFrom(dict_to_struct(payload.get("meta") or {}))
    else:
        step_event.log_event.level = "WARN"
        step_event.log_event.message = f"unknown event type: {event_type}"

    return pb.RuntimeMessage(step_event=step_event)


def build_step_result_message(
    *,
    request_id: str,
    step_id: str,
    status: str | StepStatus,
    metrics: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    error_message: str = "",
) -> pb.RuntimeMessage:
    step_id = str(step_id)
    step_result = pb.StepResult(
        request_id=request_id,
        step_id=step_id,
        status=step_status_to_enum(status),
        error_message=str(error_message or ""),
    )
    for metric_name, metric_value in (metrics or {}).items():
        try:
            step_result.metrics[str(metric_name)] = float(metric_value)
        except Exception:
            continue

    for name, artifact in (artifacts or {}).items():
        if not isinstance(artifact, Mapping):
            continue
        step_result.artifacts.append(
            pb.ArtifactItem(
                kind=str(artifact.get("kind") or "artifact"),
                name=str(name),
                uri=str(artifact.get("uri") or ""),
                meta=dict_to_struct(artifact.get("meta") or {}),
            )
        )

    for candidate in candidates or []:
        step_result.candidates.append(
            pb.QueryCandidate(
                sample_id=str(candidate.get("sample_id") or ""),
                score=float(candidate.get("score") or 0.0),
                reason=dict_to_struct(candidate.get("reason") or {}),
            )
        )

    return pb.RuntimeMessage(step_result=step_result)


def get_message_request_id(message: pb.RuntimeMessage) -> str:
    payload_type = message.WhichOneof("payload")
    if not payload_type:
        return ""
    payload = getattr(message, payload_type)
    return str(getattr(payload, "request_id", "") or "")


def set_message_request_id(message: pb.RuntimeMessage, request_id: str) -> None:
    payload_type = message.WhichOneof("payload")
    if not payload_type:
        return
    payload = getattr(message, payload_type)
    if hasattr(payload, "request_id"):
        setattr(payload, "request_id", request_id)


def parse_assign_step(assign_step: pb.AssignStep) -> dict[str, Any]:
    step_payload = assign_step.step
    step_id = _resolve_step_id(step_payload.step_id)
    round_id = str(step_payload.round_id or "")
    depends_on_step_ids = list(step_payload.depends_on_step_ids or [])
    return {
        "step_id": step_id,
        "round_id": round_id,
        "loop_id": step_payload.loop_id,
        "project_id": step_payload.project_id,
        "input_commit_id": step_payload.input_commit_id,
        "step_type": _STEP_TYPE_TO_TEXT.get(int(step_payload.step_type), ""),
        "dispatch_kind": _DISPATCH_KIND_TO_TEXT.get(int(step_payload.dispatch_kind), ""),
        "plugin_id": step_payload.plugin_id,
        "mode": _LOOP_MODE_TO_TEXT.get(int(step_payload.mode), ""),
        "query_strategy": step_payload.query_strategy,
        "resolved_params": struct_to_dict(step_payload.resolved_params),
        "resources": _resource_summary_to_dict(step_payload.resources),
        "round_index": int(step_payload.round_index or 0),
        "attempt": int(step_payload.attempt or 1),
        "depends_on_step_ids": [str(v) for v in depends_on_step_ids],
    }


def parse_data_response(data_response: pb.DataResponse) -> dict[str, Any]:
    step_id = _resolve_step_id(data_response.step_id)
    return {
        "request_id": data_response.request_id,
        "reply_to": data_response.reply_to,
        "step_id": step_id,
        "query_type": query_type_to_text(data_response.query_type),
        "payload_id": data_response.payload_id,
        "chunk_index": int(data_response.chunk_index),
        "chunk_count": int(data_response.chunk_count),
        "header_proto": bytes(data_response.header_proto),
        "payload_chunk": bytes(data_response.payload_chunk),
        "payload_total_size": int(data_response.payload_total_size),
        "payload_checksum_crc32c": int(data_response.payload_checksum_crc32c),
        "chunk_checksum_crc32c": int(data_response.chunk_checksum_crc32c),
        "next_cursor": data_response.next_cursor or None,
        "is_last_chunk": bool(data_response.is_last_chunk),
    }


def parse_upload_ticket_response(upload_ticket: pb.UploadTicketResponse) -> dict[str, Any]:
    step_id = _resolve_step_id(upload_ticket.step_id)
    return {
        "request_id": upload_ticket.request_id,
        "reply_to": upload_ticket.reply_to,
        "step_id": step_id,
        "upload_url": upload_ticket.upload_url,
        "storage_uri": upload_ticket.storage_uri,
        "headers": dict(upload_ticket.headers),
    }


def parse_error(error_payload: pb.Error) -> dict[str, Any]:
    step_id = _resolve_step_id(error_payload.step_id)
    query_type = ""
    if int(error_payload.query_type) != pb.RUNTIME_QUERY_TYPE_UNSPECIFIED:
        query_type = query_type_to_text(error_payload.query_type)
    return {
        "request_id": error_payload.request_id,
        "code": error_payload.code,
        "message": error_payload.message,
        "reply_to": error_payload.reply_to,
        "ack_for": error_payload.ack_for,
        "step_id": step_id,
        "query_type": query_type,
        "reason": error_payload.reason,
        "error": error_payload.reason or error_payload.message or error_payload.code or "runtime error",
    }
