from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from saki_api.infra.db.session import SessionLocal
from saki_api.modules.access.service.presets import init_preset_roles
from saki_api.modules.system.api.http import system
from saki_api.modules.system.service.asset_gc_scheduler import asset_gc_scheduler
from saki_api.modules.system.service.system import SystemService
from saki_api.modules.system.service.system_settings import SystemSettingsService


@dataclass(slots=True)
class SystemAppModule:
    name: str = "system"

    def register_routes(self, api_router: APIRouter) -> None:
        api_router.include_router(system.router, prefix="/system", tags=["system"])

    async def startup(self) -> None:
        async with SessionLocal() as session:
            await SystemSettingsService(session).bootstrap_defaults()
            if await SystemService(session).is_init():
                await init_preset_roles(session)
                await session.commit()
        await asset_gc_scheduler.start()

    async def shutdown(self) -> None:
        await asset_gc_scheduler.stop()


system_app_module = SystemAppModule()
