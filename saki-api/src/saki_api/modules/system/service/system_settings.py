"""
System settings service.

Provides registry-driven settings read/write with Redis cache.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.cache.redis import get_redis_client
from saki_api.modules.system.domain.setting import SystemSetting
from saki_api.modules.system.service.system_setting_keys import SystemSettingKeys
from saki_api.modules.system.service.system_settings_registry import (
    SYSTEM_SETTINGS_REGISTRY,
    SystemSettingDef,
    list_setting_defs,
)


class SystemSettingsService:
    """Service for dynamic system settings."""

    CACHE_KEY = f"{settings.REDIS_KEY_PREFIX}:system_settings:v1"
    CACHE_LOCK_KEY = f"{CACHE_KEY}:lock"
    CACHE_LOCK_TTL_SECONDS = 10
    CACHE_LOCK_WAIT_SECONDS = 5

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _acquire_cache_lock(self, *, wait_seconds: int | None = None) -> str | None:
        client = get_redis_client()
        wait = self.CACHE_LOCK_WAIT_SECONDS if wait_seconds is None else max(0, wait_seconds)
        deadline = asyncio.get_running_loop().time() + wait
        token = uuid.uuid4().hex
        while True:
            try:
                locked = await client.set(
                    self.CACHE_LOCK_KEY,
                    token,
                    nx=True,
                    ex=self.CACHE_LOCK_TTL_SECONDS,
                )
            except Exception as exc:
                logger.warning("system settings lock acquire failed error={}", exc)
                return None

            if locked:
                return token

            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.05)

    async def _release_cache_lock(self, token: str) -> None:
        client = get_redis_client()
        script = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
        try:
            await client.eval(script, 1, self.CACHE_LOCK_KEY, token)
        except Exception as exc:
            logger.warning("system settings lock release failed error={}", exc)

    @asynccontextmanager
    async def _cache_lock(self):
        token = await self._acquire_cache_lock()
        if not token:
            yield False
            return
        try:
            yield True
        finally:
            await self._release_cache_lock(token)

    @staticmethod
    def _serialize_cache_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _deserialize_cache_value(raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            # 回退：兼容非 JSON 缓存残留
            return raw

    @staticmethod
    def _normalize_bool(value: Any, *, default: bool | None = None) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            if default is not None:
                return default
            raise BadRequestAppException("invalid boolean value")
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise BadRequestAppException("invalid boolean value")

    @staticmethod
    def _normalize_number(value: Any, *, integer: bool) -> int | float:
        if integer:
            if isinstance(value, bool):
                raise BadRequestAppException("invalid integer value")
            try:
                return int(value)
            except Exception as exc:
                raise BadRequestAppException("invalid integer value") from exc
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("number is not finite")
            return number
        except Exception as exc:
            raise BadRequestAppException("invalid number value") from exc

    def _apply_constraints(self, definition: SystemSettingDef, value: Any) -> Any:
        constraints = definition.constraints or {}

        if definition.type in {"integer", "number"}:
            minimum = constraints.get("min")
            maximum = constraints.get("max")
            if minimum is not None and value < minimum:
                raise BadRequestAppException(f"{definition.key} must be >= {minimum}")
            if maximum is not None and value > maximum:
                raise BadRequestAppException(f"{definition.key} must be <= {maximum}")

        if definition.type == "string":
            min_length = constraints.get("min_length")
            max_length = constraints.get("max_length")
            if min_length is not None and len(value) < int(min_length):
                raise BadRequestAppException(f"{definition.key} length must be >= {min_length}")
            if max_length is not None and len(value) > int(max_length):
                raise BadRequestAppException(f"{definition.key} length must be <= {max_length}")

        if definition.type == "integer_array":
            min_items = constraints.get("min_items")
            max_items = constraints.get("max_items")
            if min_items is not None and len(value) < int(min_items):
                raise BadRequestAppException(f"{definition.key} items must be >= {min_items}")
            if max_items is not None and len(value) > int(max_items):
                raise BadRequestAppException(f"{definition.key} items must be <= {max_items}")

        return value

    def validate_value(self, key: str, raw_value: Any) -> Any:
        definition = SYSTEM_SETTINGS_REGISTRY.get(key)
        if not definition:
            raise BadRequestAppException(f"unknown system setting key: {key}")

        if definition.type == "boolean":
            value = self._normalize_bool(raw_value)
        elif definition.type == "string":
            value = str(raw_value or "").strip()
        elif definition.type == "integer":
            value = self._normalize_number(raw_value, integer=True)
        elif definition.type == "number":
            value = self._normalize_number(raw_value, integer=False)
        elif definition.type == "enum":
            value = str(raw_value or "").strip()
            allowed = {str(item.get("value")) for item in definition.options}
            if value not in allowed:
                raise BadRequestAppException(f"{key} must be one of {sorted(allowed)}")
        elif definition.type == "integer_array":
            source = raw_value if isinstance(raw_value, list) else [raw_value]
            values: list[int] = []
            for item in source:
                if isinstance(item, str) and "," in item:
                    segments = [seg.strip() for seg in item.split(",")]
                else:
                    segments = [item]
                for segment in segments:
                    if segment in {"", None}:
                        continue
                    values.append(int(self._normalize_number(segment, integer=True)))
            deduped: list[int] = []
            seen: set[int] = set()
            for item in values:
                if item in seen:
                    continue
                seen.add(item)
                deduped.append(item)
            value = deduped
        else:
            raise BadRequestAppException(f"unsupported setting type: {definition.type}")

        return self._apply_constraints(definition, value)

    async def bootstrap_defaults(self) -> None:
        created = 0

        for key, definition in SYSTEM_SETTINGS_REGISTRY.items():
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        SystemSetting(
                            key=key,
                            value_json={"value": definition.default},
                            updated_by=None,
                        )
                    )
                    await self.session.flush()
                    created += 1
            except IntegrityError:
                # 并发启动时可能已被其他实例插入
                continue

        await self.session.commit()
        if created:
            logger.info("system settings bootstrap created {} missing keys", created)
        await self.refresh_cache()

    async def _load_effective_values_from_db(self) -> dict[str, Any]:
        rows = await self.session.exec(select(SystemSetting))
        values = {
            key: definition.default
            for key, definition in SYSTEM_SETTINGS_REGISTRY.items()
        }

        for row in rows.all():
            definition = SYSTEM_SETTINGS_REGISTRY.get(row.key)
            if not definition:
                logger.warning("unknown system setting in db key={} (ignored)", row.key)
                continue
            raw_value = (row.value_json or {}).get("value", definition.default)
            try:
                values[row.key] = self.validate_value(row.key, raw_value)
            except BadRequestAppException:
                logger.warning(
                    "invalid system setting value in db key={} raw_value={} (fallback to default)",
                    row.key,
                    raw_value,
                )
                values[row.key] = definition.default

        return values

    async def _read_cache(self) -> dict[str, Any] | None:
        try:
            client = get_redis_client()
            raw_map = await client.hgetall(self.CACHE_KEY)
            if not raw_map:
                return None
            payload: dict[str, Any] = {}
            for key, raw_value in raw_map.items():
                payload[key] = self._deserialize_cache_value(raw_value)
            return payload
        except Exception as exc:
            logger.warning("system settings redis read failed error={}", exc)
            return None

    async def _write_cache(self, values: dict[str, Any]) -> None:
        try:
            client = get_redis_client()
            mapping = {
                key: self._serialize_cache_value(value)
                for key, value in values.items()
            }
            async with client.pipeline(transaction=True) as pipe:
                pipe.delete(self.CACHE_KEY)
                if mapping:
                    pipe.hset(self.CACHE_KEY, mapping=mapping)
                await pipe.execute()
        except Exception as exc:
            logger.warning("system settings redis write failed error={}", exc)

    async def refresh_cache(self) -> dict[str, Any]:
        async with self._cache_lock() as locked:
            values = await self._load_effective_values_from_db()
            if locked:
                await self._write_cache(values)
            return values

    async def get_values(self) -> dict[str, Any]:
        cached = await self._read_cache()
        if cached is not None:
            values = {
                key: cached.get(key, definition.default)
                for key, definition in SYSTEM_SETTINGS_REGISTRY.items()
            }
            return values
        # 缓存 miss 时尽量串行回填，降低并发覆盖概率
        async with self._cache_lock() as locked:
            cached = await self._read_cache()
            if cached is not None:
                return {
                    key: cached.get(key, definition.default)
                    for key, definition in SYSTEM_SETTINGS_REGISTRY.items()
                }

            values = await self._load_effective_values_from_db()
            if locked:
                await self._write_cache(values)
            return values

    async def get_value(self, key: str, *, default: Any = None) -> Any:
        definition = SYSTEM_SETTINGS_REGISTRY.get(key)
        if not definition:
            if default is not None:
                return default
            raise BadRequestAppException(f"unknown system setting key: {key}")

        values = await self.get_values()
        if key in values:
            return values[key]
        if default is not None:
            return default
        return definition.default

    async def get_bool(self, key: str, *, default: bool | None = None) -> bool:
        definition = SYSTEM_SETTINGS_REGISTRY.get(key)
        if not definition:
            if default is not None:
                return default
            raise BadRequestAppException(f"unknown system setting key: {key}")
        if definition.type != "boolean":
            raise BadRequestAppException(f"system setting {key} is not boolean")

        value = await self.get_value(key, default=default if default is not None else definition.default)
        return self._normalize_bool(value, default=default if default is not None else definition.default)

    async def update_values(
        self,
        values: dict[str, Any],
        *,
        updated_by: uuid.UUID | None,
    ) -> dict[str, Any]:
        async with self._cache_lock() as locked:
            if not locked:
                raise BadRequestAppException("system settings update lock unavailable, please retry")

            if not isinstance(values, dict):
                raise BadRequestAppException("settings values must be an object")

            editable_keys = {
                key for key, definition in SYSTEM_SETTINGS_REGISTRY.items()
                if definition.editable
            }
            incoming_keys = set(values.keys())
            if incoming_keys == editable_keys and incoming_keys:
                raise BadRequestAppException(
                    "global settings update is disabled, use patch payload with changed keys only"
                )

            normalized: dict[str, Any] = {}
            for key, raw_value in values.items():
                definition = SYSTEM_SETTINGS_REGISTRY.get(key)
                if not definition:
                    raise BadRequestAppException(f"unknown system setting key: {key}")
                if not definition.editable:
                    raise BadRequestAppException(f"setting is read-only: {key}")
                normalized[key] = self.validate_value(key, raw_value)

            existing: dict[str, SystemSetting] = {}
            if normalized:
                rows = await self.session.exec(
                    select(SystemSetting).where(SystemSetting.key.in_(list(normalized.keys())))
                )
                existing = {row.key: row for row in rows.all()}
            for key, value in normalized.items():
                row = existing.get(key)
                if not row:
                    row = SystemSetting(
                        key=key,
                        value_json={"value": value},
                    )
                else:
                    row.value_json = {"value": value}
                row.updated_by = updated_by
                self.session.add(row)

            await self.session.commit()

            effective_values = await self._load_effective_values_from_db()
            if locked:
                await self._write_cache(effective_values)
            return effective_values

    async def get_schema_fields(self) -> list[dict[str, Any]]:
        return [item.to_schema() for item in list_setting_defs()]

    async def get_bundle(self) -> dict[str, Any]:
        return {
            "fields": await self.get_schema_fields(),
            "values": await self.get_values(),
        }

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
