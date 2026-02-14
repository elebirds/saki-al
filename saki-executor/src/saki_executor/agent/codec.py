from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.state import TaskStatus

_ACTIVATE_SAMPLES_ENUM = getattr(pb, "ACTIVATE_SAMPLES", getattr(pb, "AUTO_LABEL", pb.CUSTOM))

_STATUS_TO_ENUM: dict[str, int] = {
    TaskStatus.PENDING.value: pb.PENDING,
    TaskStatus.DISPATCHING.value: pb.DISPATCHING,
    TaskStatus.RUNNING.value: pb.RUNNING,
    TaskStatus.RETRYING.value: pb.RETRYING,
    TaskStatus.SUCCEEDED.value: pb.SUCCEEDED,
    TaskStatus.FAILED.value: pb.FAILED,
    TaskStatus.CANCELLED.value: pb.CANCELLED,
    TaskStatus.SKIPPED.value: pb.SKIPPED,
}

_ENUM_TO_STATUS: dict[int, str] = {
    pb.PENDING: TaskStatus.PENDING.value,
    pb.DISPATCHING: TaskStatus.DISPATCHING.value,
    pb.RUNNING: TaskStatus.RUNNING.value,
    pb.RETRYING: TaskStatus.RETRYING.value,
    pb.SUCCEEDED: TaskStatus.SUCCEEDED.value,
    pb.FAILED: TaskStatus.FAILED.value,
    pb.CANCELLED: TaskStatus.CANCELLED.value,
    pb.SKIPPED: TaskStatus.SKIPPED.value,
}

_TASK_TYPE_TO_TEXT: dict[int, str] = {
    pb.TRAIN: "train",
    pb.SCORE: "score",
    pb.SELECT: "select",
    _ACTIVATE_SAMPLES_ENUM: "activate_samples",
    pb.WAIT_ANNOTATION: "wait_annotation",
    pb.MERGE: "merge",
    pb.EVAL: "eval",
    pb.UPLOAD_ARTIFACT: "upload_artifact",
    pb.CUSTOM: "custom",
}
_TEXT_TO_TASK_TYPE: dict[str, int] = {value: key for key, value in _TASK_TYPE_TO_TEXT.items()}
_TEXT_TO_TASK_TYPE["auto_label"] = _ACTIVATE_SAMPLES_ENUM

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
    pb.ACK_TYPE_ASSIGN_TASK: "assign_task",
    pb.ACK_TYPE_STOP_TASK: "stop_task",
    pb.ACK_TYPE_REQUEST: "request",
}
_TEXT_TO_ACK_TYPE: dict[str, int] = {value: key for key, value in _ACK_TYPE_TO_TEXT.items()}

_ACK_REASON_TO_TEXT: dict[int, str] = {
    pb.ACK_REASON_REGISTERED: "registered",
    pb.ACK_REASON_ACCEPTED: "accepted",
    pb.ACK_REASON_EXECUTOR_BUSY: "executor_busy",
    pb.ACK_REASON_STOPPING: "stopping",
    pb.ACK_REASON_TASK_NOT_RUNNING: "task_not_running",
    pb.ACK_REASON_REJECTED: "rejected",
}
_TEXT_TO_ACK_REASON: dict[str, int] = {value: key for key, value in _ACK_REASON_TO_TEXT.items()}


def _resolve_step_id(step_id: str | None, task_id: str | None) -> str:
    value = str(step_id or "").strip()
    if value:
        return value
    return str(task_id or "").strip()


def dict_to_struct(payload: Mapping[str, Any] | None) -> Struct:
    struct = Struct()
    if payload:
        struct.update(dict(payload))
    return struct


def struct_to_dict(payload: Struct | None) -> dict[str, Any]:
    if payload is None or not payload.ListFields():
        return {}
    return dict(MessageToDict(payload, preserving_proto_field_name=True))


def task_status_to_enum(status: str | TaskStatus) -> int:
    raw = status.value if isinstance(status, TaskStatus) else str(status or "").lower()
    return _STATUS_TO_ENUM.get(raw, pb.PENDING)


def status_enum_to_text(status: int) -> str:
    return _ENUM_TO_STATUS.get(int(status), TaskStatus.PENDING.value)


def text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").lower(), pb.LABELS)


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
                supported_task_types=[str(v) for v in (item.get("supported_task_types") or [])],
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
    current_task_id: str | None,
    resources: Mapping[str, Any],
) -> pb.RuntimeMessage:
    step_id = str(current_task_id or "")
    return pb.RuntimeMessage(
        heartbeat=pb.Heartbeat(
            request_id=request_id,
            executor_id=executor_id,
            busy=busy,
            current_step_id=step_id,
            current_task_id=step_id,
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
    task_id: str,
    query_type: str,
    project_id: str,
    commit_id: str,
    cursor: str | None,
    limit: int,
) -> pb.RuntimeMessage:
    step_id = str(task_id)
    return pb.RuntimeMessage(
        data_request=pb.DataRequest(
            request_id=request_id,
            step_id=step_id,
            task_id=step_id,
            query_type=text_to_query_type(query_type),
            project_id=project_id,
            commit_id=commit_id,
            cursor=str(cursor or ""),
            limit=int(limit),
        )
    )


def build_upload_ticket_request_message(
    *,
    request_id: str,
    task_id: str,
    artifact_name: str,
    content_type: str,
) -> pb.RuntimeMessage:
    step_id = str(task_id)
    return pb.RuntimeMessage(
        upload_ticket_request=pb.UploadTicketRequest(
            request_id=request_id,
            step_id=step_id,
            task_id=step_id,
            artifact_name=artifact_name,
            content_type=content_type,
        )
    )


def build_task_event_message(
    *,
    request_id: str,
    task_id: str,
    seq: int,
    ts: int,
    event_type: str,
    payload: Mapping[str, Any],
) -> pb.RuntimeMessage:
    step_id = str(task_id)
    task_event = pb.TaskEvent(
        request_id=request_id,
        step_id=step_id,
        task_id=step_id,
        seq=int(seq),
        ts=int(ts),
    )

    if event_type == "status":
        task_event.status_event.status = task_status_to_enum(str(payload.get("status") or ""))
        if payload.get("reason") is not None:
            task_event.status_event.reason = str(payload.get("reason"))
    elif event_type == "log":
        task_event.log_event.level = str(payload.get("level") or "")
        task_event.log_event.message = str(payload.get("message") or "")
    elif event_type == "progress":
        task_event.progress_event.epoch = int(payload.get("epoch") or 0)
        task_event.progress_event.step = int(payload.get("step") or 0)
        task_event.progress_event.total_steps = int(payload.get("total_steps") or 0)
        task_event.progress_event.eta_sec = int(payload.get("eta_sec") or 0)
    elif event_type == "metric":
        task_event.metric_event.step = int(payload.get("step") or 0)
        task_event.metric_event.epoch = int(payload.get("epoch") or 0)
        for metric_name, metric_value in (payload.get("metrics") or {}).items():
            try:
                task_event.metric_event.metrics[str(metric_name)] = float(metric_value)
            except Exception:
                continue
    elif event_type == "artifact":
        artifact = task_event.artifact_event.artifact
        artifact.kind = str(payload.get("kind") or "artifact")
        artifact.name = str(payload.get("name") or "")
        artifact.uri = str(payload.get("uri") or "")
        artifact.meta.CopyFrom(dict_to_struct(payload.get("meta") or {}))
    else:
        task_event.log_event.level = "WARN"
        task_event.log_event.message = f"unknown event type: {event_type}"

    return pb.RuntimeMessage(task_event=task_event)


def build_task_result_message(
    *,
    request_id: str,
    task_id: str,
    status: str | TaskStatus,
    metrics: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    error_message: str = "",
) -> pb.RuntimeMessage:
    step_id = str(task_id)
    task_result = pb.TaskResult(
        request_id=request_id,
        step_id=step_id,
        task_id=step_id,
        status=task_status_to_enum(status),
        error_message=str(error_message or ""),
    )
    for metric_name, metric_value in (metrics or {}).items():
        try:
            task_result.metrics[str(metric_name)] = float(metric_value)
        except Exception:
            continue

    for name, artifact in (artifacts or {}).items():
        if not isinstance(artifact, Mapping):
            continue
        task_result.artifacts.append(
            pb.ArtifactItem(
                kind=str(artifact.get("kind") or "artifact"),
                name=str(name),
                uri=str(artifact.get("uri") or ""),
                meta=dict_to_struct(artifact.get("meta") or {}),
            )
        )

    for candidate in candidates or []:
        task_result.candidates.append(
            pb.QueryCandidate(
                sample_id=str(candidate.get("sample_id") or ""),
                score=float(candidate.get("score") or 0.0),
                reason=dict_to_struct(candidate.get("reason") or {}),
            )
        )

    return pb.RuntimeMessage(task_result=task_result)


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


def parse_assign_task(assign_task: pb.AssignTask) -> dict[str, Any]:
    task = assign_task.task
    step_id = _resolve_step_id(task.step_id, task.task_id)
    round_id = str(task.round_id or task.job_id or "")
    depends_on_step_ids = list(task.depends_on_step_ids or task.depends_on_task_ids or [])
    return {
        "step_id": step_id,
        "round_id": round_id,
        "task_id": step_id,
        "job_id": round_id,
        "loop_id": task.loop_id,
        "project_id": task.project_id,
        "source_commit_id": task.source_commit_id,
        "task_type": _TASK_TYPE_TO_TEXT.get(int(task.task_type), "custom"),
        "plugin_id": task.plugin_id,
        "mode": _LOOP_MODE_TO_TEXT.get(int(task.mode), "active_learning"),
        "query_strategy": task.query_strategy,
        "params": struct_to_dict(task.params),
        "resources": _resource_summary_to_dict(task.resources),
        "round_index": int(task.round_index or 0),
        "attempt": int(task.attempt or 1),
        "depends_on_step_ids": [str(v) for v in depends_on_step_ids],
        "depends_on_task_ids": [str(v) for v in depends_on_step_ids],
    }


def parse_data_response(data_response: pb.DataResponse) -> dict[str, Any]:
    step_id = _resolve_step_id(data_response.step_id, data_response.task_id)
    items: list[dict[str, Any]] = []
    for item in data_response.items:
        item_type = item.WhichOneof("item")
        if item_type == "label_item":
            label = item.label_item
            items.append({"id": label.id, "name": label.name, "color": label.color})
        elif item_type == "sample_item":
            sample = item.sample_item
            items.append(
                {
                    "id": sample.id,
                    "asset_hash": sample.asset_hash,
                    "download_url": sample.download_url,
                    "width": int(sample.width),
                    "height": int(sample.height),
                    "meta": struct_to_dict(sample.meta),
                }
            )
        elif item_type == "annotation_item":
            ann = item.annotation_item
            obb = struct_to_dict(ann.obb)
            items.append(
                {
                    "id": ann.id,
                    "sample_id": ann.sample_id,
                    "category_id": ann.category_id,
                    "bbox_xywh": [float(v) for v in ann.bbox_xywh],
                    "obb": obb or None,
                    "source": ann.source,
                    "confidence": float(ann.confidence),
                }
            )
    return {
        "request_id": data_response.request_id,
        "reply_to": data_response.reply_to,
        "step_id": step_id,
        "task_id": step_id,
        "query_type": query_type_to_text(data_response.query_type),
        "items": items,
        "next_cursor": data_response.next_cursor or None,
    }


def parse_upload_ticket_response(upload_ticket: pb.UploadTicketResponse) -> dict[str, Any]:
    step_id = _resolve_step_id(upload_ticket.step_id, upload_ticket.task_id)
    return {
        "request_id": upload_ticket.request_id,
        "reply_to": upload_ticket.reply_to,
        "step_id": step_id,
        "task_id": step_id,
        "upload_url": upload_ticket.upload_url,
        "storage_uri": upload_ticket.storage_uri,
        "headers": dict(upload_ticket.headers),
    }


def parse_error(error_payload: pb.Error) -> dict[str, Any]:
    step_id = _resolve_step_id(error_payload.step_id, error_payload.task_id)
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
        "task_id": step_id,
        "query_type": query_type,
        "reason": error_payload.reason,
        "error": error_payload.reason or error_payload.message or error_payload.code or "runtime error",
    }
