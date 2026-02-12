from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.modules.project.api.http import (
    branch,
    commit,
    label,
    project,
)


@dataclass(slots=True)
class ProjectAppModule:
    name: str = "project"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(project.router, prefix="/projects", tags=["projects"])
        api_router.include_router(label.router, prefix="/labels", tags=["labels"])
        api_router.include_router(commit.router, prefix="/commits", tags=["commits"])
        api_router.include_router(branch.router, prefix="/branches", tags=["branches"])

    async def startup(self) -> None:  # pragma: no cover - no runtime side effects
        return None

    async def shutdown(self) -> None:  # pragma: no cover - no runtime side effects
        return None


project_app_module = ProjectAppModule()
