from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.modules.annotation.api.http import annotation
from saki_api.modules.annotation.extensions.factory import AnnotationSystemFactory


@dataclass(slots=True)
class AnnotationAppModule:
    name: str = "annotation"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(annotation.router, prefix="/annotations", tags=["annotations"])

    async def startup(self) -> None:
        AnnotationSystemFactory.discover_all()

    async def shutdown(self) -> None:  # pragma: no cover - no runtime side effects
        return None


annotation_app_module = AnnotationAppModule()
