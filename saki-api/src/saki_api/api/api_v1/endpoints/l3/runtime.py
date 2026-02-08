"""
Runtime executor observability endpoints.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException, ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models import Permissions
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.models.l3.runtime_executor_stats import RuntimeExecutorStats
from saki_api.schemas.l3.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsPoint,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimeExecutorSummary,
    RuntimePluginCatalogResponse,
    RuntimePluginRead,
)
from saki_api.services.runtime_plugin_catalog import aggregate_runtime_plugins

router = APIRouter()
_STATS_RANGE_CONFIG: dict[RuntimeExecutorStatsRange, tuple[timedelta, int]] = {
    "30m": (timedelta(minutes=30), 10),
    "1h": (timedelta(hours=1), 20),
    "6h": (timedelta(hours=6), 60),
    "24h": (timedelta(hours=24), 300),
    "7d": (timedelta(days=7), 3600),
}


async def _ensure_runtime_read_permission(session: AsyncSession, current_user_id: str) -> None:
    checker = PermissionChecker(session)
    allowed = await checker.check(user_id=current_user_id, permission=Permissions.JOB_READ)
    if not allowed:
        allowed = await checker.check(user_id=current_user_id, permission=Permissions.PROJECT_READ_ALL)
    if not allowed:
        raise ForbiddenAppException("Permission denied: runtime:read")


@router.get("/runtime/executors", response_model=RuntimeExecutorListResponse)
async def list_runtime_executors(
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)

    rows = await session.exec(
        select(RuntimeExecutor).order_by(RuntimeExecutor.is_online.desc(), RuntimeExecutor.last_seen_at.desc())
    )
    executors = list(rows.all())
    dispatcher_snapshot = await runtime_dispatcher.metrics_snapshot()

    items: list[RuntimeExecutorRead] = []
    latest_heartbeat_at: datetime | None = None
    total_count = len(executors)
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

        pending = await runtime_dispatcher.executor_pending_snapshot(
            executor_id=executor.executor_id,
            current_job_id=executor.current_job_id,
        )
        items.append(
            RuntimeExecutorRead(
                id=executor.id,
                executor_id=executor.executor_id,
                version=executor.version,
                status=executor.status,
                is_online=executor.is_online,
                current_job_id=executor.current_job_id,
                plugin_ids=executor.plugin_ids or {},
                resources=executor.resources or {},
                last_seen_at=executor.last_seen_at,
                last_error=executor.last_error,
                pending_assign_count=pending["pending_assign_count"],
                pending_stop_count=pending["pending_stop_count"],
            )
        )

    return RuntimeExecutorListResponse(
        summary=RuntimeExecutorSummary(
            total_count=total_count,
            online_count=online_count,
            busy_count=busy_count,
            available_count=available_count,
            availability_rate=(available_count / total_count) if total_count > 0 else 0.0,
            pending_assign_count=int(dispatcher_snapshot["pending_assign_count"]),
            pending_stop_count=int(dispatcher_snapshot["pending_stop_count"]),
            latest_heartbeat_at=latest_heartbeat_at,
        ),
        items=items,
    )


@router.get("/runtime/executors/stats", response_model=RuntimeExecutorStatsResponse)
async def get_runtime_executor_stats(
        range: RuntimeExecutorStatsRange = "30m",
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)

    window, bucket_seconds = _STATS_RANGE_CONFIG[range]
    now = datetime.now(timezone.utc)
    start_at = now - window

    rows = await session.exec(
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
        range=range,
        bucket_seconds=bucket_seconds,
        points=points,
    )


@router.get("/runtime/executors/{executor_id}", response_model=RuntimeExecutorRead)
async def get_runtime_executor(
        *,
        executor_id: str,
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)

    row = await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
    executor = row.first()
    if not executor:
        raise NotFoundAppException(f"RuntimeExecutor {executor_id} not found")

    pending = await runtime_dispatcher.executor_pending_snapshot(
        executor_id=executor.executor_id,
        current_job_id=executor.current_job_id,
    )
    return RuntimeExecutorRead(
        id=executor.id,
        executor_id=executor.executor_id,
        version=executor.version,
        status=executor.status,
        is_online=executor.is_online,
        current_job_id=executor.current_job_id,
        plugin_ids=executor.plugin_ids or {},
        resources=executor.resources or {},
        last_seen_at=executor.last_seen_at,
        last_error=executor.last_error,
        pending_assign_count=pending["pending_assign_count"],
        pending_stop_count=pending["pending_stop_count"],
    )


@router.get("/runtime/plugins", response_model=RuntimePluginCatalogResponse)
async def list_runtime_plugins(
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)

    rows = await session.exec(
        select(RuntimeExecutor).order_by(RuntimeExecutor.is_online.desc(), RuntimeExecutor.last_seen_at.desc())
    )
    executors = list(rows.all())
    items = [RuntimePluginRead(**item) for item in aggregate_runtime_plugins(executors)]
    return RuntimePluginCatalogResponse(items=items)
