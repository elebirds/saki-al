from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.state import JobStatus

_STATUS_TO_ENUM: dict[str, int] = {
    JobStatus.CREATED.value: pb.CREATED,
    JobStatus.QUEUED.value: pb.QUEUED,
    JobStatus.RUNNING.value: pb.RUNNING,
    JobStatus.STOPPING.value: pb.STOPPING,
    JobStatus.STOPPED.value: pb.STOPPED,
    JobStatus.SUCCEEDED.value: pb.SUCCEEDED,
    JobStatus.FAILED.value: pb.FAILED,
    "pending": pb.QUEUED,
    "success": pb.SUCCEEDED,
    "cancelled": pb.STOPPED,
}

_ENUM_TO_STATUS: dict[int, str] = {
    pb.CREATED: JobStatus.CREATED.value,
    pb.QUEUED: JobStatus.QUEUED.value,
    pb.RUNNING: JobStatus.RUNNING.value,
    pb.STOPPING: JobStatus.STOPPING.value,
    pb.STOPPED: JobStatus.STOPPED.value,
    pb.SUCCEEDED: JobStatus.SUCCEEDED.value,
    pb.FAILED: JobStatus.FAILED.value,
}

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
    if payload is None or not payload.ListFields():
        return {}
    return dict(MessageToDict(payload, preserving_proto_field_name=True))


def job_status_to_enum(status: str | JobStatus) -> int:
    raw = status.value if isinstance(status, JobStatus) else str(status or "").lower()
    return _STATUS_TO_ENUM.get(raw, pb.QUEUED)


def status_enum_to_text(status: int) -> str:
    return _ENUM_TO_STATUS.get(int(status), JobStatus.QUEUED.value)


def text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").lower(), pb.LABELS)


def query_type_to_text(query_type: int) -> str:
    return _QUERY_TYPE_TO_TEXT.get(int(query_type), "labels")


def _dict_to_resource_summary(resources: Mapping[str, Any] | None) -> pb.ResourceSummary:
    payload = resources or {}
    return pb.ResourceSummary(
        gpu_count=int(payload.get("gpu_count") or 0),
        gpu_device_ids=[int(item) for item in (payload.get("gpu_device_ids") or [])],
        cpu_workers=int(payload.get("cpu_workers") or 0),
        memory_mb=int(payload.get("memory_mb") or 0),
    )


def _resource_summary_to_dict(resources: pb.ResourceSummary) -> dict[str, Any]:
    return {
        "gpu_count": int(resources.gpu_count),
        "gpu_device_ids": [int(item) for item in resources.gpu_device_ids],
        "cpu_workers": int(resources.cpu_workers),
        "memory_mb": int(resources.memory_mb),
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
                supported_job_types=[str(v) for v in (item.get("supported_job_types") or [])],
                supported_strategies=[str(v) for v in (item.get("supported_strategies") or [])],
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
    current_job_id: str | None,
    resources: Mapping[str, Any],
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        heartbeat=pb.Heartbeat(
            request_id=request_id,
            executor_id=executor_id,
            busy=busy,
            current_job_id=str(current_job_id or ""),
            resources=_dict_to_resource_summary(resources),
        )
    )


def build_ack_message(*, request_id: str, ack_for: str, ok: bool, message: str) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        ack=pb.Ack(
            request_id=request_id,
            ack_for=ack_for,
            status=pb.OK if ok else pb.ERROR,
            message=message,
        )
    )


def build_data_request_message(
    *,
    request_id: str,
    job_id: str,
    query_type: str,
    project_id: str,
    commit_id: str,
    cursor: str | None,
    limit: int,
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        data_request=pb.DataRequest(
            request_id=request_id,
            job_id=job_id,
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
    job_id: str,
    artifact_name: str,
    content_type: str,
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        upload_ticket_request=pb.UploadTicketRequest(
            request_id=request_id,
            job_id=job_id,
            artifact_name=artifact_name,
            content_type=content_type,
        )
    )


def build_job_event_message(
    *,
    request_id: str,
    job_id: str,
    seq: int,
    ts: int,
    event_type: str,
    payload: Mapping[str, Any],
) -> pb.RuntimeMessage:
    job_event = pb.JobEvent(
        request_id=request_id,
        job_id=job_id,
        seq=int(seq),
        ts=int(ts),
    )

    if event_type == "status":
        job_event.status_event.status = job_status_to_enum(str(payload.get("status") or ""))
        if payload.get("reason") is not None:
            job_event.status_event.reason = str(payload.get("reason"))
    elif event_type == "log":
        job_event.log_event.level = str(payload.get("level") or "")
        job_event.log_event.message = str(payload.get("message") or "")
    elif event_type == "progress":
        job_event.progress_event.epoch = int(payload.get("epoch") or 0)
        job_event.progress_event.step = int(payload.get("step") or 0)
        job_event.progress_event.total_steps = int(payload.get("total_steps") or 0)
        job_event.progress_event.eta_sec = int(payload.get("eta_sec") or 0)
    elif event_type == "metric":
        job_event.metric_event.step = int(payload.get("step") or 0)
        job_event.metric_event.epoch = int(payload.get("epoch") or 0)
        for metric_name, metric_value in (payload.get("metrics") or {}).items():
            try:
                job_event.metric_event.metrics[str(metric_name)] = float(metric_value)
            except Exception:
                continue
    elif event_type == "artifact":
        artifact = job_event.artifact_event.artifact
        artifact.kind = str(payload.get("kind") or "artifact")
        artifact.name = str(payload.get("name") or "")
        artifact.uri = str(payload.get("uri") or "")
        artifact.meta.CopyFrom(dict_to_struct(payload.get("meta") or {}))
    else:
        job_event.log_event.level = "WARN"
        job_event.log_event.message = f"unknown event type: {event_type}"

    return pb.RuntimeMessage(job_event=job_event)


def build_job_result_message(
    *,
    request_id: str,
    job_id: str,
    status: str | JobStatus,
    metrics: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    error_message: str = "",
) -> pb.RuntimeMessage:
    job_result = pb.JobResult(
        request_id=request_id,
        job_id=job_id,
        status=job_status_to_enum(status),
        error_message=str(error_message or ""),
    )
    for metric_name, metric_value in (metrics or {}).items():
        try:
            job_result.metrics[str(metric_name)] = float(metric_value)
        except Exception:
            continue

    for name, artifact in (artifacts or {}).items():
        if not isinstance(artifact, Mapping):
            continue
        job_result.artifacts.append(
            pb.ArtifactItem(
                kind=str(artifact.get("kind") or "artifact"),
                name=str(name),
                uri=str(artifact.get("uri") or ""),
                meta=dict_to_struct(artifact.get("meta") or {}),
            )
        )

    for candidate in candidates or []:
        job_result.candidates.append(
            pb.QueryCandidate(
                sample_id=str(candidate.get("sample_id") or ""),
                score=float(candidate.get("score") or 0.0),
                reason=dict_to_struct(candidate.get("reason") or {}),
            )
        )

    return pb.RuntimeMessage(job_result=job_result)


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


def parse_assign_job(assign_job: pb.AssignJob) -> dict[str, Any]:
    job = assign_job.job
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "loop_id": job.loop_id,
        "source_commit_id": job.source_commit_id,
        "job_type": _JOB_TYPE_TO_TEXT.get(int(job.job_type), "train_detection"),
        "plugin_id": job.plugin_id,
        "mode": _JOB_MODE_TO_TEXT.get(int(job.mode), "active_learning"),
        "query_strategy": job.query_strategy,
        "params": struct_to_dict(job.params),
        "resources": _resource_summary_to_dict(job.resources),
    }


def parse_data_response(data_response: pb.DataResponse) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in data_response.items:
        item_type = item.WhichOneof("item")
        if item_type == "label_item":
            label = item.label_item
            items.append(
                {
                    "id": label.id,
                    "name": label.name,
                    "color": label.color,
                }
            )
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
        "job_id": data_response.job_id,
        "query_type": query_type_to_text(data_response.query_type),
        "items": items,
        "next_cursor": data_response.next_cursor or None,
    }


def parse_upload_ticket_response(upload_ticket: pb.UploadTicketResponse) -> dict[str, Any]:
    return {
        "request_id": upload_ticket.request_id,
        "reply_to": upload_ticket.reply_to,
        "job_id": upload_ticket.job_id,
        "upload_url": upload_ticket.upload_url,
        "storage_uri": upload_ticket.storage_uri,
        "headers": dict(upload_ticket.headers),
    }


def parse_error(error_payload: pb.Error) -> dict[str, Any]:
    details = struct_to_dict(error_payload.details)
    return {
        "request_id": error_payload.request_id,
        "code": error_payload.code,
        "message": error_payload.message,
        "details": details,
        "reply_to": str(details.get("reply_to") or details.get("request_id") or ""),
        "ack_for": str(details.get("ack_for") or ""),
        "error": error_payload.message or error_payload.code or "runtime error",
    }
