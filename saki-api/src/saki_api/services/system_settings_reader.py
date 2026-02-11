"""
Global singleton reader for system settings.
"""

from __future__ import annotations

from typing import Any

from saki_api.db.session import SessionLocal
from saki_api.services.system_setting_keys import SystemSettingKeys
from saki_api.services.system_settings import SystemSettingsService


class SystemSettingsReader:
    _instance: "SystemSettingsReader | None" = None

    def __new__(cls) -> "SystemSettingsReader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_values(self) -> dict[str, Any]:
        async with SessionLocal() as session:
            return await SystemSettingsService(session).get_values()

    async def get_value(self, key: str, *, default: Any = None) -> Any:
        async with SessionLocal() as session:
            return await SystemSettingsService(session).get_value(key, default=default)

    async def get_bool(self, key: str, *, default: bool | None = None) -> bool:
        async with SessionLocal() as session:
            return await SystemSettingsService(session).get_bool(key, default=default)

    async def get_simulation_defaults(self) -> dict[str, Any]:
        values = await self.get_values()
        return {
            "seed_ratio": float(values.get(SystemSettingKeys.SIMULATION_SEED_RATIO, 0.05)),
            "step_ratio": float(values.get(SystemSettingKeys.SIMULATION_STEP_RATIO, 0.05)),
            "max_rounds": int(values.get(SystemSettingKeys.SIMULATION_MAX_ROUNDS, 20)),
            "seeds": list(values.get(SystemSettingKeys.SIMULATION_SEEDS, [0, 1, 2, 3, 4])),
            "random_baseline_enabled": bool(
                values.get(SystemSettingKeys.SIMULATION_RANDOM_BASELINE_ENABLED, True)
            ),
        }


system_settings_reader = SystemSettingsReader()
