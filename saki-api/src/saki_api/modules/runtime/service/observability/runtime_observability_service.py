"""
Runtime observability read service.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.infra.dispatcher_admin.client import DispatcherAdminClient
from saki_api.modules.runtime.api.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsPoint,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimeExecutorSummary,
    RuntimePluginCatalogResponse,
    RuntimePluginRead,
)
from saki_api.modules.runtime.domain.runtime_executor import RuntimeExecutor
from saki_api.modules.runtime.domain.runtime_executor_stats import RuntimeExecutorStats
from saki_api.modules.runtime.repo.runtime_executor import RuntimeExecutorRepository
from saki_api.modules.runtime.repo.runtime_executor_stats import RuntimeExecutorStatsRepository
from saki_api.modules.runtime.service.catalog.runtime_plugin_catalog_service import (
    aggregate_runtime_plugins,
)

_STATS_RANGE_CONFIG: dict[RuntimeExecutorStatsRange, tuple[timedelta, int]] = {
    "30m": (timedelta(minutes=30), 10),
    "1h": (timedelta(hours=1), 20),
    "6h": (timedelta(hours=6), 60),
    "24h": (timedelta(hours=24), 300),
    "7d": (timedelta(days=7), 3600),
}


class RuntimeObservabilityService:
    def __init__(
            self,
            session: AsyncSession,
            dispatcher_admin_client: DispatcherAdminClient | None = None,
    ):
        self.session = session
        self.runtime_executor_repo = RuntimeExecutorRepository(session)
        self.runtime_executor_stats_repo = RuntimeExecutorStatsRepository(session)
        self.dispatcher_admin_client = dispatcher_admin_client

    @property
    def _dispatcher_admin_enabled(self) -> bool:
        return bool(self.dispatcher_admin_client and self.dispatcher_admin_client.enabled)

    @staticmethod
    def _parse_optional_datetime(raw: Any) -> datetime | None:
        value = str(raw or "").strip()
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None

    async def _get_dispatcher_summary_snapshot(self) -> dict[str, Any]:
        if not self._dispatcher_admin_enabled:
            return {
                "online_count": 0,
                "busy_count": 0,
                "pending_assign_count": 0,
                "pending_stop_count": 0,
                "latest_heartbeat_at": None,
            }

        try:
            summary = await self.dispatcher_admin_client.get_runtime_summary()  # type: ignore[union-attr]
            return {
                "online_count": int(summary.online_executors),
                "busy_count": int(summary.busy_executors),
                "pending_assign_count": int(summary.pending_assign_count),
                "pending_stop_count": int(summary.pending_stop_count),
                "latest_heartbeat_at": self._parse_optional_datetime(summary.latest_heartbeat_at),
            }
        except Exception:
            pass

        return {
            "online_count": 0,
            "busy_count": 0,
            "pending_assign_count": 0,
            "pending_stop_count": 0,
            "latest_heartbeat_at": None,
        }

    async def _get_executor_pending_snapshot_map(self, executors: list[RuntimeExecutor]) -> dict[str, dict[str, int]]:
        if not executors:
            return {}

        if self._dispatcher_admin_enabled:
            try:
                rows = await self.dispatcher_admin_client.list_executors()  # type: ignore[union-attr]
                return {
                    str(item.executor_id): {
                        "pending_assign_count": int(item.pending_assign_count),
                        "pending_stop_count": int(item.pending_stop_count),
                    }
                    for item in rows.items
                    if str(item.executor_id or "").strip()
                }
            except Exception:
                pass

        return {
            executor.executor_id: {
                "pending_assign_count": 0,
                "pending_stop_count": 0,
            }
            for executor in executors
        }

    @staticmethod
    def _to_runtime_executor_read(
            *,
            executor: RuntimeExecutor,
            pending_assign_count: int,
            pending_stop_count: int,
    ) -> RuntimeExecutorRead:
        return RuntimeExecutorRead(
            id=executor.id,
            executor_id=executor.executor_id,
            version=executor.version,
            status=executor.status,
            is_online=executor.is_online,
            current_task_id=executor.current_task_id,
            plugin_ids=executor.plugin_ids or {},
            resources=executor.resources or {},
            last_seen_at=executor.last_seen_at,
            last_error=executor.last_error,
            pending_assign_count=pending_assign_count,
            pending_stop_count=pending_stop_count,
        )

    async def _list_executors_ordered(self) -> list[RuntimeExecutor]:
        return await self.runtime_executor_repo.list_ordered()

    @staticmethod
    def _build_executor_summary(
            *,
            executors: list[RuntimeExecutor],
            dispatcher_snapshot: dict[str, Any],
    ) -> RuntimeExecutorSummary:
        latest_heartbeat_at: datetime | None = None
        online_count = int(dispatcher_snapshot.get("online_count", 0))
        busy_count = int(dispatcher_snapshot.get("busy_count", 0))
        available_count = 0

        for executor in executors:
            if executor.is_online and executor.status not in {"busy", "reserved", "offline"}:
                available_count += 1
            if executor.last_seen_at and (latest_heartbeat_at is None or executor.last_seen_at > latest_heartbeat_at):
                latest_heartbeat_at = executor.last_seen_at

        dispatcher_latest_heartbeat_at = dispatcher_snapshot.get("latest_heartbeat_at")
        if isinstance(dispatcher_latest_heartbeat_at, datetime):
            latest_heartbeat_at = dispatcher_latest_heartbeat_at

        total_count = len(executors)
        return RuntimeExecutorSummary(
            total_count=total_count,
            online_count=online_count,
            busy_count=busy_count,
            available_count=available_count,
            availability_rate=(available_count / total_count) if total_count > 0 else 0.0,
            pending_assign_count=int(dispatcher_snapshot.get("pending_assign_count", 0)),
            pending_stop_count=int(dispatcher_snapshot.get("pending_stop_count", 0)),
            latest_heartbeat_at=latest_heartbeat_at,
        )

    async def list_executors(self) -> RuntimeExecutorListResponse:
        executors = await self._list_executors_ordered()
        dispatcher_snapshot = await self._get_dispatcher_summary_snapshot()
        pending_snapshot_map = await self._get_executor_pending_snapshot_map(executors)

        items: list[RuntimeExecutorRead] = []
        for executor in executors:
            pending = pending_snapshot_map.get(executor.executor_id, {})
            items.append(
                self._to_runtime_executor_read(
                    executor=executor,
                    pending_assign_count=int(pending.get("pending_assign_count", 0)),
                    pending_stop_count=int(pending.get("pending_stop_count", 0)),
                )
            )

        return RuntimeExecutorListResponse(
            summary=self._build_executor_summary(
                executors=executors,
                dispatcher_snapshot=dispatcher_snapshot,
            ),
            items=items,
        )

    async def get_executor(self, executor_id: str) -> RuntimeExecutorRead:
        executor = await self.runtime_executor_repo.get_by_executor_id(executor_id)
        if not executor:
            raise NotFoundAppException(f"RuntimeExecutor {executor_id} not found")

        pending: dict[str, int] = {
            "pending_assign_count": 0,
            "pending_stop_count": 0,
        }
        if self._dispatcher_admin_enabled:
            try:
                response = await self.dispatcher_admin_client.get_executor(executor_id)  # type: ignore[union-attr]
                if response.item and str(response.item.executor_id or "").strip():
                    pending = {
                        "pending_assign_count": int(response.item.pending_assign_count),
                        "pending_stop_count": int(response.item.pending_stop_count),
                    }
            except Exception:
                pass

        return self._to_runtime_executor_read(
            executor=executor,
            pending_assign_count=int(pending.get("pending_assign_count", 0)),
            pending_stop_count=int(pending.get("pending_stop_count", 0)),
        )

    async def get_executor_stats(self, stats_range: RuntimeExecutorStatsRange) -> RuntimeExecutorStatsResponse:
        window, bucket_seconds = _STATS_RANGE_CONFIG[stats_range]
        now = datetime.now(timezone.utc)
        start_at = now - window

        snapshots = await self.runtime_executor_stats_repo.list_since(start_at)

        bucket_to_snapshot: dict[int, RuntimeExecutorStats] = {}
        for snapshot in snapshots:
            ts = snapshot.ts
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            epoch = int(ts.timestamp())
            bucket_epoch = epoch - (epoch % bucket_seconds)
            previous = bucket_to_snapshot.get(bucket_epoch)
            if previous is None or previous.ts < snapshot.ts:
                bucket_to_snapshot[bucket_epoch] = snapshot

        points: list[RuntimeExecutorStatsPoint] = []
        for bucket_epoch in sorted(bucket_to_snapshot.keys()):
            snapshot = bucket_to_snapshot[bucket_epoch]
            points.append(
                RuntimeExecutorStatsPoint(
                    ts=datetime.fromtimestamp(bucket_epoch, tz=timezone.utc),
                    total_count=snapshot.total_count,
                    online_count=snapshot.online_count,
                    busy_count=snapshot.busy_count,
                    available_count=snapshot.available_count,
                    availability_rate=snapshot.availability_rate,
                    pending_assign_count=snapshot.pending_assign_count,
                    pending_stop_count=snapshot.pending_stop_count,
                )
            )

        return RuntimeExecutorStatsResponse(
            range=stats_range,
            bucket_seconds=bucket_seconds,
            points=points,
        )

    async def list_plugins(self) -> RuntimePluginCatalogResponse:
        executors = await self._list_executors_ordered()
        items = [RuntimePluginRead(**asdict(item)) for item in aggregate_runtime_plugins(executors)]
        return RuntimePluginCatalogResponse(items=items)
