"""
Background scheduler for orphaned asset cleanup.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.core.redis import get_redis_client
from saki_api.repositories.storage.asset import AssetRepository
from saki_api.services.system.system_setting_keys import SystemSettingKeys
from saki_api.services.system.system_settings_reader import system_settings_reader
from saki_api.utils.storage import StorageError, get_storage_provider


class AssetGcScheduler:
    LOCK_KEY = f"{settings.REDIS_KEY_PREFIX}:asset-gc:lock"
    LOCK_TTL_SECONDS = 3600

    def __init__(self, session_local=SessionLocal):
        self._session_local = session_local
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_run_at: datetime | None = None
        self._storage = get_storage_provider()
        self._lock_token: str | None = None

    async def _acquire_lock(self) -> bool:
        token = uuid.uuid4().hex
        try:
            locked = await get_redis_client().set(
                self.LOCK_KEY,
                token,
                nx=True,
                ex=self.LOCK_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("asset gc lock acquire failed error={}", exc)
            return False
        if locked:
            self._lock_token = token
            return True
        return False

    async def _release_lock(self) -> None:
        token = self._lock_token
        if not token:
            return
        script = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
        try:
            await get_redis_client().eval(script, 1, self.LOCK_KEY, token)
        except Exception as exc:
            logger.warning("asset gc lock release failed error={}", exc)
        finally:
            self._lock_token = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="asset-gc-scheduler")
        logger.info("asset gc scheduler started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("asset gc scheduler stopped")

    async def run_once(self) -> None:
        await self._cleanup_once()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                values = await system_settings_reader.get_values()
                enabled = bool(values.get(SystemSettingKeys.MAINTENANCE_ASSET_GC_ENABLED, False))
                interval_hours = max(
                    1,
                    int(values.get(SystemSettingKeys.MAINTENANCE_ASSET_GC_INTERVAL_HOURS, 24)),
                )

                should_run = False
                if enabled:
                    if self._last_run_at is None:
                        should_run = True
                    else:
                        should_run = (datetime.now(UTC) - self._last_run_at) >= timedelta(hours=interval_hours)
                if should_run:
                    await self._cleanup_once()
                    self._last_run_at = datetime.now(UTC)
            except Exception as exc:
                logger.exception("asset gc scheduler loop failed error={}", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                continue

    async def _cleanup_once(self) -> None:
        if not await self._acquire_lock():
            logger.debug("asset gc skipped: lock not acquired")
            return

        async with self._session_local() as session:
            try:
                values = await system_settings_reader.get_values()

                enabled = bool(values.get(SystemSettingKeys.MAINTENANCE_ASSET_GC_ENABLED, False))
                if not enabled:
                    logger.debug("asset gc skipped: disabled")
                    return

                orphan_age_hours = max(
                    1,
                    int(values.get(SystemSettingKeys.MAINTENANCE_ASSET_GC_ORPHAN_AGE_HOURS, 24 * 7)),
                )
                older_than = datetime.now(UTC) - timedelta(hours=orphan_age_hours)

                repo = AssetRepository(session)
                orphaned_assets = await repo.get_orphaned_assets_older_than(
                    older_than=older_than,
                    limit=10000,
                )

                if not orphaned_assets:
                    logger.info("asset gc finished deleted=0 failed=0 candidates=0")
                    return

                deleted = 0
                failed = 0
                for asset in orphaned_assets:
                    try:
                        self._storage.delete_object(asset.path)
                        await repo.delete(asset.id)
                        deleted += 1
                    except StorageError as exc:
                        failed += 1
                        logger.warning(
                            "asset gc storage delete failed asset_id={} path={} error={}",
                            asset.id,
                            asset.path,
                            exc,
                        )
                    except Exception as exc:
                        failed += 1
                        logger.warning(
                            "asset gc failed asset_id={} path={} error={}",
                            asset.id,
                            asset.path,
                            exc,
                        )

                await session.commit()
                logger.info(
                    "asset gc finished deleted={} failed={} candidates={}",
                    deleted,
                    failed,
                    len(orphaned_assets),
                )
            finally:
                await self._release_lock()


asset_gc_scheduler = AssetGcScheduler()
