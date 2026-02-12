"""L3 Job/Task endpoints router (aggregated)."""

from __future__ import annotations

from fastapi import APIRouter

from saki_api.modules.runtime.api.http.endpoints import job_command_endpoints, job_query_endpoints

router = APIRouter()
router.include_router(job_command_endpoints.router)
router.include_router(job_query_endpoints.router)

create_job = job_command_endpoints.create_job
stop_job = job_command_endpoints.stop_job
stop_task = job_command_endpoints.stop_task
get_job = job_query_endpoints.get_job
list_job_tasks = job_query_endpoints.list_job_tasks
get_task = job_query_endpoints.get_task
get_task_events = job_query_endpoints.get_task_events
get_task_metric_series = job_query_endpoints.get_task_metric_series
get_task_candidates = job_query_endpoints.get_task_candidates
get_task_artifacts = job_query_endpoints.get_task_artifacts
get_task_artifact_download_url = job_query_endpoints.get_task_artifact_download_url

__all__ = [
    "router",
    "create_job",
    "stop_job",
    "stop_task",
    "get_job",
    "list_job_tasks",
    "get_task",
    "get_task_events",
    "get_task_metric_series",
    "get_task_candidates",
    "get_task_artifacts",
    "get_task_artifact_download_url",
]
