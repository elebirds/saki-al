"""
Runtime executor observability endpoints.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.db.session import get_session
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.schemas.l3.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorSummary,
)

router = APIRouter()


@router.get("/runtime/executors", response_model=RuntimeExecutorListResponse)
async def list_runtime_executors(
        session: AsyncSession = Depends(get_session),
):
    rows = await session.exec(
        select(RuntimeExecutor).order_by(RuntimeExecutor.is_online.desc(), RuntimeExecutor.last_seen_at.desc())
    )
    executors = list(rows.all())
    dispatcher_snapshot = await runtime_dispatcher.metrics_snapshot()

    items: list[RuntimeExecutorRead] = []
    latest_heartbeat_at: datetime | None = None
    online_count = 0
    busy_count = 0

    for executor in executors:
        if executor.is_online:
            online_count += 1
            if executor.last_seen_at and (latest_heartbeat_at is None or executor.last_seen_at > latest_heartbeat_at):
                latest_heartbeat_at = executor.last_seen_at
        if executor.status in {"busy", "reserved"}:
            busy_count += 1

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
            online_count=online_count,
            busy_count=busy_count,
            pending_assign_count=int(dispatcher_snapshot["pending_assign_count"]),
            pending_stop_count=int(dispatcher_snapshot["pending_stop_count"]),
            latest_heartbeat_at=latest_heartbeat_at,
        ),
        items=items,
    )


@router.get("/runtime/executors/{executor_id}", response_model=RuntimeExecutorRead)
async def get_runtime_executor(
        *,
        executor_id: str,
        session: AsyncSession = Depends(get_session),
):
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
