from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.core.config import settings
from saki_api.infra.grpc.runtime_control import runtime_grpc_server
from saki_api.modules.runtime.api.http import (
    model as l3_model,
    query as l3_query,
    runtime as l3_runtime,
)
from saki_api.modules.runtime.api.http.endpoints import (
    loop_action_endpoints,
    prediction_set_endpoints,
    round_step_command_endpoints,
    round_step_query_endpoints,
    snapshot_endpoints,
)


@dataclass(slots=True)
class RuntimeAppModule:
    name: str = "runtime"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(round_step_command_endpoints.router, prefix="", tags=["rounds", "steps"])
        api_router.include_router(round_step_query_endpoints.router, prefix="", tags=["rounds", "steps"])
        api_router.include_router(l3_query.router, prefix="", tags=["loops", "rounds", "steps"])
        api_router.include_router(l3_runtime.router, prefix="", tags=["runtime"])
        api_router.include_router(loop_action_endpoints.router, prefix="", tags=["loops", "annotation-batches"])
        api_router.include_router(snapshot_endpoints.router, prefix="", tags=["loops", "annotation-batches"])
        api_router.include_router(prediction_set_endpoints.router, prefix="", tags=["loops", "annotation-batches"])
        api_router.include_router(l3_model.router, prefix="", tags=["models"])

    async def startup(self) -> None:
        if settings.RUNTIME_DOMAIN_GRPC_SERVER_ENABLED:
            await runtime_grpc_server.start()

    async def shutdown(self) -> None:
        if settings.RUNTIME_DOMAIN_GRPC_SERVER_ENABLED:
            await runtime_grpc_server.stop()


runtime_app_module = RuntimeAppModule()
