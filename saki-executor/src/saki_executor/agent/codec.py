from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_executor.grpc_gen import runtime_control_pb2 as pb


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


def _text_to_status(status: str | None) -> int:
    return _TEXT_TO_STATUS.get((status or "").lower(), pb.QUEUED)


def _ack_text_to_enum(status: str | None) -> int:
    return pb.OK if (status or "").lower() == "ok" else pb.ERROR


def _ack_enum_to_text(status: int) -> str:
    return "ok" if status == pb.OK else "error"


def _text_to_job_type(job_type: str | None) -> int:
    return _TEXT_TO_JOB_TYPE.get((job_type or "").lower(), pb.TRAIN_DETECTION)


def _job_type_to_text(job_type: int) -> str:
    return _JOB_TYPE_TO_TEXT.get(int(job_type), "train_detection")


def _text_to_job_mode(mode: str | None) -> int:
    return _TEXT_TO_JOB_MODE.get((mode or "").lower(), pb.ACTIVE_LEARNING)


def _job_mode_to_text(mode: int) -> str:
    return _JOB_MODE_TO_TEXT.get(int(mode), "active_learning")


def _text_to_query_type(query_type: str | None) -> int:
    return _TEXT_TO_QUERY_TYPE.get((query_type or "").lower(), pb.LABELS)


def _query_type_to_text(query_type: int) -> str:
    return _QUERY_TYPE_TO_TEXT.get(int(query_type), "labels")


def dict_to_runtime_message(message: dict[str, Any]) -> pb.RuntimeMessage:
    msg_type = str(message.get("type") or "")

    if msg_type == "register":
        plugins: list[pb.PluginCapability] = []
        for item in (message.get("plugins") or []):
            plugins.append(
                pb.PluginCapability(
                    plugin_id=str(item.get("plugin_id") or ""),
                    version=str(item.get("version") or ""),
                    supported_job_types=[str(v) for v in (item.get("supported_job_types") or [])],
                    supported_strategies=[str(v) for v in (item.get("supported_strategies") or [])],
                )
            )
        return pb.RuntimeMessage(
            register=pb.Register(
                request_id=str(message.get("request_id") or ""),
                executor_id=str(message.get("executor_id") or ""),
                version=str(message.get("version") or ""),
                plugins=plugins,
                resources=_dict_to_resource_summary(message.get("resources") or {}),
            )
        )

    if msg_type == "heartbeat":
        return pb.RuntimeMessage(
            heartbeat=pb.Heartbeat(
                request_id=str(message.get("request_id") or ""),
                executor_id=str(message.get("executor_id") or ""),
                busy=bool(message.get("busy", False)),
                current_job_id=str(message.get("current_job_id") or ""),
                resources=_dict_to_resource_summary(message.get("resources") or {}),
            )
        )

    if msg_type == "ack":
        return pb.RuntimeMessage(
            ack=pb.Ack(
                request_id=str(message.get("request_id") or ""),
                ack_for=str(message.get("ack_for") or ""),
                status=_ack_text_to_enum(str(message.get("status") or "")),
                message=str(message.get("message") or ""),
            )
        )

    if msg_type == "job_event":
        payload = message.get("payload") or {}
        job_event = pb.JobEvent(
            request_id=str(message.get("request_id") or ""),
            job_id=str(message.get("job_id") or ""),
            seq=int(message.get("seq") or 0),
            ts=int(message.get("ts") or 0),
        )
        event_type = str(message.get("event_type") or "")
        if event_type == "status":
            job_event.status_event.status = _text_to_status(str(payload.get("status") or ""))
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
            metrics = payload.get("metrics") or {}
            for metric_name, metric_value in metrics.items():
                job_event.metric_event.metrics[str(metric_name)] = float(metric_value)
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

    if msg_type == "job_result":
        job_result = pb.JobResult(
            request_id=str(message.get("request_id") or ""),
            job_id=str(message.get("job_id") or ""),
            status=_text_to_status(str(message.get("status") or "")),
            error_message=str(message.get("error_message") or ""),
        )
        metrics = message.get("metrics") or {}
        for metric_name, metric_value in metrics.items():
            try:
                job_result.metrics[str(metric_name)] = float(metric_value)
            except Exception:
                continue
        artifacts = message.get("artifacts") or {}
        for name, artifact in artifacts.items():
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
        for candidate in (message.get("candidates") or []):
            job_result.candidates.append(
                pb.QueryCandidate(
                    sample_id=str(candidate.get("sample_id") or ""),
                    score=float(candidate.get("score") or 0.0),
                    reason=dict_to_struct(candidate.get("reason") or {}),
                )
            )
        return pb.RuntimeMessage(job_result=job_result)

    if msg_type == "data_request":
        return pb.RuntimeMessage(
            data_request=pb.DataRequest(
                request_id=str(message.get("request_id") or ""),
                job_id=str(message.get("job_id") or ""),
                query_type=_text_to_query_type(str(message.get("query_type") or "")),
                project_id=str(message.get("project_id") or ""),
                commit_id=str(message.get("commit_id") or ""),
                cursor=str(message.get("cursor") or ""),
                limit=int(message.get("limit") or 0),
            )
        )

    if msg_type == "upload_ticket_request":
        return pb.RuntimeMessage(
            upload_ticket_request=pb.UploadTicketRequest(
                request_id=str(message.get("request_id") or ""),
                job_id=str(message.get("job_id") or ""),
                artifact_name=str(message.get("artifact_name") or ""),
                content_type=str(message.get("content_type") or ""),
            )
        )

    if msg_type == "error":
        return pb.RuntimeMessage(
            error=pb.Error(
                request_id=str(message.get("request_id") or ""),
                code=str(message.get("code") or ""),
                message=str(message.get("message") or ""),
                details=dict_to_struct(message.get("details") or {}),
            )
        )

    raise ValueError(f"unsupported runtime message type: {msg_type}")


def runtime_message_to_dict(message: pb.RuntimeMessage) -> dict[str, Any]:
    payload_type = message.WhichOneof("payload")

    if payload_type == "ack":
        payload = message.ack
        return {
            "type": "ack",
            "request_id": payload.request_id,
            "ack_for": payload.ack_for,
            "status": _ack_enum_to_text(int(payload.status)),
            "message": payload.message,
        }

    if payload_type == "assign_job":
        payload = message.assign_job
        job = payload.job
        return {
            "type": "assign_job",
            "request_id": payload.request_id,
            "job": {
                "job_id": job.job_id,
                "project_id": job.project_id,
                "loop_id": job.loop_id,
                "source_commit_id": job.source_commit_id,
                "job_type": _job_type_to_text(job.job_type),
                "plugin_id": job.plugin_id,
                "mode": _job_mode_to_text(job.mode),
                "query_strategy": job.query_strategy,
                "params": struct_to_dict(job.params),
                "resources": _resource_summary_to_dict(job.resources),
            },
        }

    if payload_type == "stop_job":
        payload = message.stop_job
        return {
            "type": "stop_job",
            "request_id": payload.request_id,
            "job_id": payload.job_id,
            "reason": payload.reason,
        }

    if payload_type == "data_response":
        payload = message.data_response
        items: list[dict[str, Any]] = []
        for item in payload.items:
            item_type = item.WhichOneof("item")
            if item_type == "label_item":
                label_item = item.label_item
                items.append(
                    {
                        "id": label_item.id,
                        "name": label_item.name,
                        "color": label_item.color,
                    }
                )
            elif item_type == "sample_item":
                sample_item = item.sample_item
                items.append(
                    {
                        "id": sample_item.id,
                        "asset_hash": sample_item.asset_hash,
                        "download_url": sample_item.download_url,
                        "width": int(sample_item.width),
                        "height": int(sample_item.height),
                        "meta": struct_to_dict(sample_item.meta),
                    }
                )
            elif item_type == "annotation_item":
                annotation_item = item.annotation_item
                obb = struct_to_dict(annotation_item.obb)
                items.append(
                    {
                        "id": annotation_item.id,
                        "sample_id": annotation_item.sample_id,
                        "category_id": annotation_item.category_id,
                        "bbox_xywh": [float(v) for v in annotation_item.bbox_xywh],
                        "obb": obb or None,
                        "source": annotation_item.source,
                        "confidence": float(annotation_item.confidence),
                    }
                )
        return {
            "type": "data_response",
            "request_id": payload.request_id,
            "reply_to": payload.reply_to,
            "job_id": payload.job_id,
            "query_type": _query_type_to_text(payload.query_type),
            "items": items,
            "next_cursor": payload.next_cursor or None,
        }

    if payload_type == "upload_ticket_response":
        payload = message.upload_ticket_response
        return {
            "type": "upload_ticket_response",
            "request_id": payload.request_id,
            "reply_to": payload.reply_to,
            "job_id": payload.job_id,
            "upload_url": payload.upload_url,
            "storage_uri": payload.storage_uri,
            "headers": dict(payload.headers),
        }

    if payload_type == "error":
        payload = message.error
        details = struct_to_dict(payload.details)
        return {
            "type": "error",
            "request_id": payload.request_id,
            "code": payload.code,
            "message": payload.message,
            "details": details,
            "reply_to": str(details.get("reply_to") or ""),
        }

    if payload_type == "heartbeat":
        payload = message.heartbeat
        return {
            "type": "heartbeat",
            "request_id": payload.request_id,
            "executor_id": payload.executor_id,
            "busy": payload.busy,
            "current_job_id": payload.current_job_id,
            "resources": _resource_summary_to_dict(payload.resources),
        }

    if payload_type == "register":
        payload = message.register
        return {
            "type": "register",
            "request_id": payload.request_id,
            "executor_id": payload.executor_id,
            "version": payload.version,
        }

    raise ValueError(f"unsupported incoming runtime payload: {payload_type}")
