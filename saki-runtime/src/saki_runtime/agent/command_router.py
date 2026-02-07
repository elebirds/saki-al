from __future__ import annotations

from loguru import logger

from saki_runtime.agent.messages import (
    build_job_created_result,
    build_job_status_result,
    build_query_result,
    job_type_from_proto,
    resources_from_proto,
    struct_to_dict,
)
from saki_runtime.grpc_gen import runtime_agent_pb2 as pb2
from pydantic import ValidationError

from saki_runtime.core.exceptions import invalid_argument
from saki_runtime.jobs.manager import JobManager
from saki_runtime.schemas.jobs import JobCreateRequest
from saki_runtime.schemas.enums import JobStatus
from saki_runtime.schemas.query import QueryRequest
from saki_runtime.services.query import query_service


class CommandRouter:
    def __init__(self, job_manager: JobManager):
        self.job_manager = job_manager

    async def handle(self, command: pb2.Command) -> pb2.AgentMessage | None:
        if not command:
            return None

        request_id = command.request_id
        name = command.WhichOneof("payload")

        if name == "create_job":
            payload = command.create_job
            if not payload.job_id:
                raise invalid_argument("create_job requires job_id")
            if not payload.project_id:
                raise invalid_argument("create_job requires project_id")
            if not payload.source_commit_id:
                raise invalid_argument("create_job requires source_commit_id")
            if not payload.plugin_id:
                raise invalid_argument("create_job requires plugin_id")
            try:
                req = JobCreateRequest(
                    job_id=payload.job_id,
                    job_type=job_type_from_proto(payload.job_type),
                    project_id=payload.project_id,
                    source_commit_id=payload.source_commit_id,
                    plugin_id=payload.plugin_id,
                    params=struct_to_dict(payload.params),
                    resources=resources_from_proto(payload.resources),
                )
            except ValidationError as e:
                raise invalid_argument("Invalid create_job payload", {"errors": e.errors()})
            except Exception as e:
                raise invalid_argument("Invalid create_job payload", {"error": str(e)})
            resp = await self.job_manager.create_job(req)
            return build_job_created_result(request_id, resp.job_id, resp.status)

        if name == "start_job":
            payload = command.start_job
            job_id = payload.job_id
            if not job_id:
                raise invalid_argument("start_job requires job_id")
            await self.job_manager.start_job(job_id)
            return build_job_status_result(request_id, job_id, JobStatus.RUNNING)

        if name == "stop_job":
            payload = command.stop_job
            job_id = payload.job_id
            if not job_id:
                raise invalid_argument("stop_job requires job_id")
            await self.job_manager.stop_job(job_id)
            return build_job_status_result(request_id, job_id, JobStatus.STOPPED)

        if name == "query_samples":
            payload = command.query_samples
            if not payload.project_id:
                raise invalid_argument("query_samples requires project_id")
            if not payload.source_commit_id:
                raise invalid_argument("query_samples requires source_commit_id")
            if not payload.plugin_id:
                raise invalid_argument("query_samples requires plugin_id")
            if payload.topk <= 0:
                raise invalid_argument("query_samples requires topk >= 1")
            try:
                req = QueryRequest(
                    project_id=payload.project_id,
                    plugin_id=payload.plugin_id,
                    model_ref={
                        "job_id": payload.model_ref.job_id,
                        "artifact_name": payload.model_ref.artifact_name or "best.pt",
                    },
                    source_commit_id=payload.source_commit_id,
                    unit=payload.unit or "image",
                    strategy=payload.strategy or "uncertainty",
                    topk=payload.topk,
                    params=struct_to_dict(payload.params),
                )
            except ValidationError as e:
                raise invalid_argument("Invalid query_samples payload", {"errors": e.errors()})
            except Exception as e:
                raise invalid_argument("Invalid query_samples payload", {"error": str(e)})
            candidates = await query_service.query_samples(req)
            payload = [c.model_dump() for c in candidates]
            return build_query_result(request_id, req.model_ref.job_id, payload)

        logger.warning(f"Unknown command: {name}")
        return None
