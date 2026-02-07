from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_runtime.core.config import settings
from saki_runtime.core.exceptions import RuntimeErrorBase
from saki_runtime.grpc_gen import runtime_agent_pb2 as pb2
from saki_runtime.schemas.enums import ErrorCode as RuntimeErrorCode
from saki_runtime.schemas.enums import EventType, JobStatus, JobType
from saki_runtime.schemas.events import (
    ArtifactPayload,
    EventEnvelope,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    StatusPayload,
)
from saki_runtime.schemas.resources import CPUResource, GPUResource, JobResources


def dict_to_struct(data: Dict[str, Any]) -> Struct:
    msg = Struct()
    if data:
        msg.update(data)
    return msg


def struct_to_dict(msg: Struct) -> Dict[str, Any]:
    if not msg:
        return {}
    return MessageToDict(msg, preserving_proto_field_name=True)


def job_status_to_proto(status: JobStatus) -> pb2.JobStatus:
    mapping = {
        JobStatus.CREATED: pb2.CREATED,
        JobStatus.QUEUED: pb2.QUEUED,
        JobStatus.RUNNING: pb2.RUNNING,
        JobStatus.STOPPING: pb2.STOPPING,
        JobStatus.STOPPED: pb2.STOPPED,
        JobStatus.SUCCEEDED: pb2.SUCCEEDED,
        JobStatus.FAILED: pb2.FAILED,
    }
    return mapping.get(status, pb2.JOB_STATUS_UNSPECIFIED)


def job_type_from_proto(job_type: pb2.JobType) -> JobType:
    mapping = {
        pb2.TRAIN_DETECTION: JobType.TRAIN_DETECTION,
        pb2.SCORE_UNLABELED: JobType.SCORE_UNLABELED,
        pb2.EXPORT_MODEL: JobType.EXPORT_MODEL,
    }
    return mapping.get(job_type, JobType.TRAIN_DETECTION)


def job_type_to_proto(job_type: JobType) -> pb2.JobType:
    mapping = {
        JobType.TRAIN_DETECTION: pb2.TRAIN_DETECTION,
        JobType.SCORE_UNLABELED: pb2.SCORE_UNLABELED,
        JobType.EXPORT_MODEL: pb2.EXPORT_MODEL,
    }
    return mapping.get(job_type, pb2.JOB_TYPE_UNSPECIFIED)


def error_code_to_proto(code: RuntimeErrorCode) -> pb2.ErrorCode:
    mapping = {
        RuntimeErrorCode.INVALID_ARGUMENT: pb2.INVALID_ARGUMENT,
        RuntimeErrorCode.NOT_FOUND: pb2.NOT_FOUND,
        RuntimeErrorCode.CONFLICT: pb2.CONFLICT,
        RuntimeErrorCode.UNAUTHORIZED: pb2.UNAUTHORIZED,
        RuntimeErrorCode.FORBIDDEN: pb2.FORBIDDEN,
        RuntimeErrorCode.UNAVAILABLE: pb2.UNAVAILABLE,
        RuntimeErrorCode.INTERNAL: pb2.INTERNAL,
    }
    return mapping.get(code, pb2.ERROR_CODE_UNSPECIFIED)


def resources_to_proto(resources: JobResources) -> pb2.Resources:
    cpu_workers = 0
    if resources.cpu:
        cpu_workers = resources.cpu.workers
    return pb2.Resources(
        gpu_count=resources.gpu.count,
        gpu_device_ids=list(resources.gpu.device_ids),
        cpu_workers=cpu_workers,
        memory_mb=resources.memory_mb or 0,
    )


def resources_from_proto(resources: pb2.Resources) -> JobResources:
    cpu = CPUResource(workers=resources.cpu_workers) if resources.cpu_workers else None
    return JobResources(
        gpu=GPUResource(count=resources.gpu_count, device_ids=list(resources.gpu_device_ids)),
        cpu=cpu,
        memory_mb=resources.memory_mb or None,
    )


def build_register(plugins: Iterable[Dict[str, Any]], resources: pb2.Resources) -> pb2.AgentMessage:
    plugin_msgs: List[pb2.PluginInfo] = []
    for plugin in plugins:
        plugin_msgs.append(
            pb2.PluginInfo(
                id=plugin.get("id", ""),
                version=plugin.get("version", ""),
                capabilities=list(plugin.get("capabilities") or []),
            )
        )
    register = pb2.Register(
        agent_id=settings.RUNTIME_AGENT_ID,
        version=settings.RUNTIME_VERSION,
        plugins=plugin_msgs,
        resources=resources,
    )
    return pb2.AgentMessage(register=register)


def build_heartbeat(resources: pb2.Resources) -> pb2.AgentMessage:
    heartbeat = pb2.Heartbeat(
        agent_id=settings.RUNTIME_AGENT_ID,
        ts=int(time.time()),
        resources=resources,
    )
    return pb2.AgentMessage(heartbeat=heartbeat)


def build_ack(request_id: str, status: pb2.AckStatus, message: str = "") -> pb2.AgentMessage:
    ack = pb2.Ack(request_id=request_id, status=status, message=message)
    return pb2.AgentMessage(ack=ack)


def build_error(request_id: str, exc: Exception, details: Optional[Dict[str, Any]] = None) -> pb2.AgentMessage:
    if isinstance(exc, RuntimeErrorBase):
        code = error_code_to_proto(exc.error_code)
        message = exc.message
        details = details or exc.details or {}
    else:
        code = pb2.INTERNAL
        message = str(exc)
        details = details or {}

    err = pb2.Error(
        request_id=request_id,
        code=code,
        message=message,
        details=dict_to_struct(details),
    )
    return pb2.AgentMessage(error=err)


def build_event_message(event: EventEnvelope) -> pb2.AgentMessage:
    payload_type = event.type
    kwargs: Dict[str, Any] = {}

    if payload_type == EventType.LOG:
        payload = LogPayload.model_validate(event.payload)
        kwargs["log"] = pb2.LogEvent(
            level=payload.level,
            message=payload.message,
            logger=payload.logger or "",
        )
    elif payload_type == EventType.PROGRESS:
        payload = ProgressPayload.model_validate(event.payload)
        kwargs["progress"] = pb2.ProgressEvent(
            epoch=payload.epoch,
            step=payload.step,
            total_steps=payload.total_steps,
            eta_sec=payload.eta_sec or 0,
        )
    elif payload_type == EventType.METRIC:
        payload = MetricPayload.model_validate(event.payload)
        kwargs["metric"] = pb2.MetricEvent(
            step=payload.step,
            epoch=payload.epoch or 0,
            metrics=dict_to_struct(payload.metrics),
        )
    elif payload_type == EventType.ARTIFACT:
        payload = ArtifactPayload.model_validate(event.payload)
        kwargs["artifact"] = pb2.ArtifactEvent(
            kind=payload.kind,
            name=payload.name,
            uri=payload.uri,
            meta=dict_to_struct(payload.meta or {}),
        )
    elif payload_type == EventType.STATUS:
        payload = StatusPayload.model_validate(event.payload)
        kwargs["status"] = pb2.StatusEvent(
            status=job_status_to_proto(payload.status),
            reason=payload.reason or "",
        )
    else:
        kwargs["log"] = pb2.LogEvent(level="WARN", message=f"Unknown event type: {event.type}", logger="runtime")

    event_msg = pb2.Event(
        job_id=event.job_id,
        seq=event.seq,
        ts=event.ts,
        **kwargs,
    )
    return pb2.AgentMessage(event=event_msg)


def build_job_created_result(request_id: str, job_id: str, status: JobStatus) -> pb2.AgentMessage:
    result = pb2.Result(
        request_id=request_id,
        job_created=pb2.JobCreated(job_id=job_id, status=job_status_to_proto(status)),
    )
    return pb2.AgentMessage(result=result)


def build_job_status_result(request_id: str, job_id: str, status: JobStatus) -> pb2.AgentMessage:
    result = pb2.Result(
        request_id=request_id,
        job_status=pb2.JobStatusResult(job_id=job_id, status=job_status_to_proto(status)),
    )
    return pb2.AgentMessage(result=result)


def build_query_result(
    request_id: str,
    model_job_id: str,
    candidates: Iterable[Dict[str, Any]],
) -> pb2.AgentMessage:
    items = []
    for cand in candidates:
        items.append(
            pb2.QueryCandidate(
                sample_id=cand.get("sample_id", ""),
                score=float(cand.get("score", 0.0)),
                reason=dict_to_struct(cand.get("reason") or {}),
            )
        )
    result = pb2.Result(
        request_id=request_id,
        query_result=pb2.QueryResult(model_job_id=model_job_id, candidates=items),
    )
    return pb2.AgentMessage(result=result)

