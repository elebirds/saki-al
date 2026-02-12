from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.modules.access.api.http import auth, permissions, roles, users


@dataclass(slots=True)
class AccessAppModule:
    name: str = "access"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
        api_router.include_router(users.router, prefix="/users", tags=["users"])
        api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
        api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])

    async def startup(self) -> None:  # pragma: no cover - no runtime side effects
        return None

    async def shutdown(self) -> None:  # pragma: no cover - no runtime side effects
        return None


access_app_module = AccessAppModule()
