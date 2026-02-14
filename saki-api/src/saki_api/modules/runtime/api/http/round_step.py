"""L3 Round/Step endpoints router (aggregated)."""

from __future__ import annotations

from fastapi import APIRouter

from saki_api.modules.runtime.api.http.endpoints import (
    round_step_command_endpoints,
    round_step_query_endpoints,
)

router = APIRouter()
router.include_router(round_step_command_endpoints.router)
router.include_router(round_step_query_endpoints.router)

create_round = round_step_command_endpoints.create_round
stop_round = round_step_command_endpoints.stop_round
stop_step = round_step_command_endpoints.stop_step
get_round = round_step_query_endpoints.get_round
list_round_steps = round_step_query_endpoints.list_round_steps
get_step = round_step_query_endpoints.get_step
get_step_events = round_step_query_endpoints.get_step_events
get_step_metric_series = round_step_query_endpoints.get_step_metric_series
get_step_candidates = round_step_query_endpoints.get_step_candidates
get_step_artifacts = round_step_query_endpoints.get_step_artifacts
get_step_artifact_download_url = round_step_query_endpoints.get_step_artifact_download_url

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
