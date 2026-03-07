from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.modules.storage.api.http import asset, dataset, sample


@dataclass(slots=True)
class StorageAppModule:
    name: str = "storage"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(asset.router, prefix="/assets", tags=["assets"])
        api_router.include_router(dataset.router, prefix="/datasets", tags=["datasets"])
        api_router.include_router(sample.router, prefix="/samples", tags=["samples"])

    async def startup(self) -> None:  # pragma: no cover - no runtime side effects
        return None

    async def shutdown(self) -> None:  # pragma: no cover - no runtime side effects
        return None


storage_app_module = StorageAppModule()
