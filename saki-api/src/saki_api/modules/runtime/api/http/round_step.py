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
