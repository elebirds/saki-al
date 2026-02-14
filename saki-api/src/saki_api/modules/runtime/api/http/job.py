"""L3 Round/Step endpoints router (aggregated)."""

from __future__ import annotations

from fastapi import APIRouter

from saki_api.modules.runtime.api.http.endpoints import job_command_endpoints, job_query_endpoints

router = APIRouter()
router.include_router(job_command_endpoints.router)
router.include_router(job_query_endpoints.router)

create_round = job_command_endpoints.create_round
stop_round = job_command_endpoints.stop_round
stop_step = job_command_endpoints.stop_step
get_round = job_query_endpoints.get_round
list_round_steps = job_query_endpoints.list_round_steps
get_step = job_query_endpoints.get_step
get_step_events = job_query_endpoints.get_step_events
get_step_metric_series = job_query_endpoints.get_step_metric_series
get_step_candidates = job_query_endpoints.get_step_candidates
get_step_artifacts = job_query_endpoints.get_step_artifacts
get_step_artifact_download_url = job_query_endpoints.get_step_artifact_download_url

__all__ = [
    "router",
    "create_round",
    "stop_round",
    "stop_step",
    "get_round",
    "list_round_steps",
    "get_step",
    "get_step_events",
    "get_step_metric_series",
    "get_step_candidates",
    "get_step_artifacts",
    "get_step_artifact_download_url",
]
