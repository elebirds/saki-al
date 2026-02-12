"""
Runtime observability read service.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.models.l3.runtime_executor_stats import RuntimeExecutorStats
from saki_api.schemas.runtime.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsPoint,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimeExecutorSummary,
    RuntimePluginCatalogResponse,
    RuntimePluginRead,
)
from saki_api.services.runtime.runtime_plugin_catalog import aggregate_runtime_plugins

_STATS_RANGE_CONFIG: dict[RuntimeExecutorStatsRange, tuple[timedelta, int]] = {
    "30m": (timedelta(minutes=30), 10),
    "1h": (timedelta(hours=1), 20),
    "6h": (timedelta(hours=6), 60),
    "24h": (timedelta(hours=24), 300),
    "7d": (timedelta(days=7), 3600),
}


class RuntimeObservabilityService:
    def __init__(self, session: AsyncSession):
        self.session = session

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
        rows = await self.session.exec(
            select(RuntimeExecutor).order_by(RuntimeExecutor.is_online.desc(), RuntimeExecutor.last_seen_at.desc())
        )
        return list(rows.all())

    @staticmethod
    def _build_executor_summary(
            *,
            executors: list[RuntimeExecutor],
            dispatcher_snapshot: dict,
    ) -> RuntimeExecutorSummary:
        latest_heartbeat_at: datetime | None = None
        online_count = 0
        busy_count = 0
        available_count = 0

        for executor in executors:
            if executor.is_online:
                online_count += 1
                if executor.last_seen_at and (latest_heartbeat_at is None or executor.last_seen_at > latest_heartbeat_at):
                    latest_heartbeat_at = executor.last_seen_at
            if executor.status in {"busy", "reserved"}:
                busy_count += 1
            if executor.is_online and executor.status not in {"busy", "reserved", "offline"}:
                available_count += 1

        total_count = len(executors)
        return RuntimeExecutorSummary(
            total_count=total_count,
            online_count=online_count,
            busy_count=busy_count,
            available_count=available_count,
            availability_rate=(available_count / total_count) if total_count > 0 else 0.0,
            pending_assign_count=int(dispatcher_snapshot["pending_assign_count"]),
            pending_stop_count=int(dispatcher_snapshot["pending_stop_count"]),
            latest_heartbeat_at=latest_heartbeat_at,
        )

    async def list_executors(self) -> RuntimeExecutorListResponse:
        executors = await self._list_executors_ordered()
        dispatcher_snapshot = await runtime_dispatcher.metrics_snapshot()

        pending_snapshots = []
        if executors:
            pending_snapshots = await asyncio.gather(
                *[
                    runtime_dispatcher.executor_pending_snapshot(
                        executor_id=executor.executor_id,
                        current_task_id=executor.current_task_id,
                    )
                    for executor in executors
                ]
            )

        items: list[RuntimeExecutorRead] = []
        for executor, pending in zip(executors, pending_snapshots):
            items.append(
                self._to_runtime_executor_read(
                    executor=executor,
                    pending_assign_count=int(pending["pending_assign_count"]),
                    pending_stop_count=int(pending["pending_stop_count"]),
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
        row = await self.session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
        executor = row.first()
        if not executor:
            raise NotFoundAppException(f"RuntimeExecutor {executor_id} not found")

        pending = await runtime_dispatcher.executor_pending_snapshot(
            executor_id=executor.executor_id,
            current_task_id=executor.current_task_id,
        )
        return self._to_runtime_executor_read(
            executor=executor,
            pending_assign_count=int(pending["pending_assign_count"]),
            pending_stop_count=int(pending["pending_stop_count"]),
        )

    async def get_executor_stats(self, stats_range: RuntimeExecutorStatsRange) -> RuntimeExecutorStatsResponse:
        window, bucket_seconds = _STATS_RANGE_CONFIG[stats_range]
        now = datetime.now(timezone.utc)
        start_at = now - window

        rows = await self.session.exec(
            select(RuntimeExecutorStats)
            .where(RuntimeExecutorStats.ts >= start_at)
            .order_by(RuntimeExecutorStats.ts.asc())
        )
        snapshots = list(rows.all())

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
        items = [RuntimePluginRead(**item) for item in aggregate_runtime_plugins(executors)]
        return RuntimePluginCatalogResponse(items=items)
