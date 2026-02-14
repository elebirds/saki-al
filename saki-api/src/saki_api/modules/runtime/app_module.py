from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.core.config import settings
from saki_api.infra.grpc.runtime_control import runtime_grpc_server
from saki_api.modules.runtime.api.http import (
    job as l3_job,
    loop_control as l3_loop_control,
    model as l3_model,
    query as l3_query,
    runtime as l3_runtime,
)


@dataclass(slots=True)
class RuntimeAppModule:
    name: str = "runtime"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(l3_job.router, prefix="", tags=["jobs"])
        api_router.include_router(l3_query.router, prefix="", tags=["loops", "jobs"])
        api_router.include_router(l3_runtime.router, prefix="", tags=["runtime"])
        api_router.include_router(l3_loop_control.router, prefix="", tags=["loops", "annotation-batches"])
        api_router.include_router(l3_model.router, prefix="", tags=["models"])

    async def startup(self) -> None:
        if settings.RUNTIME_DOMAIN_GRPC_SERVER_ENABLED:
            await runtime_grpc_server.start()

    async def shutdown(self) -> None:
        if settings.RUNTIME_DOMAIN_GRPC_SERVER_ENABLED:
            await runtime_grpc_server.stop()


runtime_app_module = RuntimeAppModule()
