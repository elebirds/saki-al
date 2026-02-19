from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.modules.importing.api.http import bulk, dataset_import, project_import, task


@dataclass(slots=True)
class ImportingAppModule:
    name: str = "importing"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(dataset_import.router, prefix="/datasets", tags=["imports"])
        api_router.include_router(project_import.router, prefix="/projects", tags=["imports"])
        api_router.include_router(bulk.dataset_router, prefix="/datasets", tags=["imports"])
        api_router.include_router(bulk.project_router, prefix="/projects", tags=["imports"])
        api_router.include_router(task.router, prefix="/imports", tags=["imports"])

    async def startup(self) -> None:  # pragma: no cover
        return None

    async def shutdown(self) -> None:  # pragma: no cover
        return None


importing_app_module = ImportingAppModule()
