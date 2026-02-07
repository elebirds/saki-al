from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc_gen import runtime_agent_pb2 as pb2
from saki_api.grpc_gen import runtime_agent_pb2_grpc as pb2_grpc
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.metric import JobSampleMetric

logger = logging.getLogger(__name__)


def dict_to_struct(data: Dict[str, Any]) -> Struct:
    msg = Struct()
    if data:
        msg.update(data)
    return msg


def struct_to_dict(msg: Struct) -> Dict[str, Any]:
    if not msg:
        return {}
    return MessageToDict(msg, preserving_proto_field_name=True)


def resources_from_dict(resources: Dict[str, Any]) -> pb2.Resources:
    gpu = resources.get("gpu") or {}
    cpu = resources.get("cpu") or {}
    return pb2.Resources(
        gpu_count=int(gpu.get("count") or 0),
        gpu_device_ids=list(gpu.get("device_ids") or []),
        cpu_workers=int(cpu.get("workers") or 0),
        memory_mb=int(resources.get("memory_mb") or 0),
    )


def resources_to_dict(resources: pb2.Resources) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "gpu": {"count": resources.gpu_count, "device_ids": list(resources.gpu_device_ids)},
        "memory_mb": resources.memory_mb or 0,
    }
    if resources.cpu_workers:
        data["cpu"] = {"workers": resources.cpu_workers}
    return data


def job_type_to_proto(job_type: str) -> pb2.JobType:
    mapping = {
        "train_detection": pb2.TRAIN_DETECTION,
        "score_unlabeled": pb2.SCORE_UNLABELED,
        "export_model": pb2.EXPORT_MODEL,
    }
    return mapping.get(job_type, pb2.JOB_TYPE_UNSPECIFIED)


def build_create_job_command(request_id: str, job: Job) -> pb2.AgentMessage:
    cmd = pb2.Command(
        request_id=request_id,
        create_job=pb2.CreateJob(
            job_id=str(job.id),
            job_type=job_type_to_proto(job.job_type),
            project_id=str(job.project_id),
            source_commit_id=str(job.source_commit_id),
            plugin_id=job.plugin_id,
            params=dict_to_struct(job.params or {}),
            resources=resources_from_dict(job.resources or {}),
        ),
    )
    return pb2.AgentMessage(command=cmd)


def build_start_job_command(request_id: str, job_id: str) -> pb2.AgentMessage:
    cmd = pb2.Command(request_id=request_id, start_job=pb2.StartJob(job_id=job_id))
    return pb2.AgentMessage(command=cmd)


def build_stop_job_command(request_id: str, job_id: str) -> pb2.AgentMessage:
    cmd = pb2.Command(request_id=request_id, stop_job=pb2.StopJob(job_id=job_id))
    return pb2.AgentMessage(command=cmd)


def build_query_samples_command(request_id: str, payload: Dict[str, Any]) -> pb2.AgentMessage:
    model_ref = payload.get("model_ref") or {}
    cmd = pb2.Command(
        request_id=request_id,
        query_samples=pb2.QuerySamples(
            project_id=str(payload.get("project_id", "")),
            source_commit_id=str(payload.get("source_commit_id", "")),
            plugin_id=payload.get("plugin_id", ""),
            model_ref=pb2.ModelRef(
                job_id=str(model_ref.get("job_id", "")),
                artifact_name=model_ref.get("artifact_name") or "best.pt",
            ),
            unit=payload.get("unit", ""),
            strategy=payload.get("strategy", ""),
            topk=int(payload.get("topk", 0)),
            params=dict_to_struct(payload.get("params") or {}),
        ),
    )
    return pb2.AgentMessage(command=cmd)


@dataclass
class RuntimeSession:
    agent_id: str
    queue: asyncio.Queue
    last_seen: float
    version: str
    plugins: Sequence[Dict[str, Any]]
    resources: Dict[str, Any]


class RuntimeSessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, RuntimeSession] = {}

    def register(self, register_msg: pb2.Register, queue: asyncio.Queue) -> None:
        if not register_msg.agent_id:
            return
        plugins = [
            {
                "id": item.id,
                "version": item.version,
                "capabilities": list(item.capabilities),
            }
            for item in register_msg.plugins
        ]
        resources = resources_to_dict(register_msg.resources)
        self.sessions[register_msg.agent_id] = RuntimeSession(
            agent_id=register_msg.agent_id,
            queue=queue,
            last_seen=time.time(),
            version=register_msg.version,
            plugins=plugins,
            resources=resources,
        )
        logger.info("Runtime agent registered: %s", register_msg.agent_id)

    def unregister(self, agent_id: str) -> None:
        if agent_id in self.sessions:
            self.sessions.pop(agent_id, None)
            logger.info("Runtime agent unregistered: %s", agent_id)

    def touch(self, agent_id: str, heartbeat: Optional[pb2.Heartbeat] = None) -> None:
        session = self.sessions.get(agent_id)
        if not session:
            return
        session.last_seen = time.time()
        if heartbeat:
            session.resources = resources_to_dict(heartbeat.resources)

    def get_any_agent(self) -> Optional[RuntimeSession]:
        if not self.sessions:
            return None
        return next(iter(self.sessions.values()))

    async def send_command(self, agent_id: str, message: pb2.AgentMessage) -> None:
        session = self.sessions.get(agent_id)
        if not session:
            raise RuntimeError("No such runtime agent")
        await session.queue.put(message)


runtime_sessions = RuntimeSessionManager()


class EventIngestor:
    @staticmethod
    def _map_status(status: pb2.JobStatus) -> TrainingJobStatus:
        mapping = {
            pb2.CREATED: TrainingJobStatus.PENDING,
            pb2.QUEUED: TrainingJobStatus.PENDING,
            pb2.RUNNING: TrainingJobStatus.RUNNING,
            pb2.STOPPING: TrainingJobStatus.RUNNING,
            pb2.STOPPED: TrainingJobStatus.CANCELLED,
            pb2.SUCCEEDED: TrainingJobStatus.SUCCESS,
            pb2.FAILED: TrainingJobStatus.FAILED,
        }
        return mapping.get(status, TrainingJobStatus.PENDING)

    async def handle_event(self, event: pb2.Event) -> None:
        if not event.job_id:
            return
        try:
            job_uuid = uuid.UUID(event.job_id)
        except Exception:
            return

        async with SessionLocal() as session:
            job = await session.get(Job, job_uuid)
            if not job:
                return

            payload = event.WhichOneof("payload")

            if payload == "status":
                status = event.status.status
                if status != pb2.JOB_STATUS_UNSPECIFIED:
                    job.status = self._map_status(status)
            elif payload == "metric":
                metrics = job.metrics or {}
                metrics.update(struct_to_dict(event.metric.metrics))
                job.metrics = metrics
            elif payload == "progress":
                job.metrics = job.metrics or {}
                job.metrics["progress"] = {
                    "epoch": event.progress.epoch,
                    "step": event.progress.step,
                    "total_steps": event.progress.total_steps,
                    "eta_sec": event.progress.eta_sec,
                }
            elif payload == "artifact":
                artifacts = job.artifacts or {}
                name = event.artifact.name
                if name:
                    artifacts[name] = {
                        "kind": event.artifact.kind,
                        "uri": event.artifact.uri,
                        "meta": struct_to_dict(event.artifact.meta),
                    }
                    job.artifacts = artifacts

            session.add(job)
            await session.commit()

    async def handle_result(self, result: pb2.Result) -> None:
        if not result.HasField("query_result"):
            return
        payload = result.query_result
        model_job_id = payload.model_job_id
        if not model_job_id:
            return

        async with SessionLocal() as session:
            for cand in payload.candidates:
                try:
                    metric = JobSampleMetric(
                        job_id=uuid.UUID(model_job_id),
                        sample_id=uuid.UUID(cand.sample_id),
                        score=cand.score,
                        extra=struct_to_dict(cand.reason),
                        prediction_snapshot={},
                    )
                    await session.merge(metric)
                except Exception:
                    continue
            await session.commit()


event_ingestor = EventIngestor()


class AuthInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        if handler is None or handler.stream_stream is None:
            return handler
        if handler_call_details.method != "/saki.runtime.v1.RuntimeAgent/Stream":
            return handler

        async def new_stream_stream(request_iterator, context):
            metadata = dict(context.invocation_metadata())
            if metadata.get("x-internal-token") != settings.INTERNAL_TOKEN:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")
            async for response in handler.stream_stream(request_iterator, context):
                yield response

        return grpc.aio.stream_stream_rpc_method_handler(
            new_stream_stream,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


class LoggingInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        if handler is None or handler.stream_stream is None:
            return handler
        if handler_call_details.method != "/saki.runtime.v1.RuntimeAgent/Stream":
            return handler

        async def new_stream_stream(request_iterator, context):
            start = time.monotonic()
            logger.info("gRPC stream start: %s", handler_call_details.method)
            try:
                async for response in handler.stream_stream(request_iterator, context):
                    yield response
            finally:
                logger.info(
                    "gRPC stream done: %s (%.2fs)",
                    handler_call_details.method,
                    time.monotonic() - start,
                )

        return grpc.aio.stream_stream_rpc_method_handler(
            new_stream_stream,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


class RuntimeAgentService(pb2_grpc.RuntimeAgentServicer):
    async def Stream(self, request_iterator, context):
        outbox: asyncio.Queue[pb2.AgentMessage] = asyncio.Queue()
        agent_id: Optional[str] = None

        async def _reader():
            nonlocal agent_id
            async for msg in request_iterator:
                try:
                    if msg.HasField("register"):
                        agent_id = msg.register.agent_id
                        if agent_id:
                            runtime_sessions.register(msg.register, outbox)
                    elif msg.HasField("heartbeat"):
                        if agent_id:
                            runtime_sessions.touch(agent_id, msg.heartbeat)
                    elif msg.HasField("event"):
                        await event_ingestor.handle_event(msg.event)
                    elif msg.HasField("result"):
                        await event_ingestor.handle_result(msg.result)
                    elif msg.HasField("error"):
                        logger.error("Runtime error [%s]: %s", msg.error.code, msg.error.message)
                    elif msg.HasField("ack"):
                        logger.debug("Runtime ack for request %s", msg.ack.request_id)
                except Exception:
                    logger.exception("Failed to handle runtime message")

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                message = await outbox.get()
                yield message
        finally:
            reader_task.cancel()
            if agent_id:
                runtime_sessions.unregister(agent_id)


class RuntimeAgentServer:
    def __init__(self) -> None:
        self.server = grpc.aio.server(interceptors=[AuthInterceptor(), LoggingInterceptor()])
        pb2_grpc.add_RuntimeAgentServicer_to_server(RuntimeAgentService(), self.server)

    async def start(self) -> None:
        self.server.add_insecure_port(settings.RUNTIME_GRPC_BIND)
        await self.server.start()
        logger.info("gRPC runtime server listening on %s", settings.RUNTIME_GRPC_BIND)

    async def stop(self) -> None:
        await self.server.stop(1)


runtime_grpc_server = RuntimeAgentServer()
