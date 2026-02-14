"""L3 query endpoints for Loop/Job/Task runtime."""

from __future__ import annotations

import contextlib
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocketState

from saki_api.app.deps import JobServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.http.support.task_event_stream import (
    authenticate_stream_token,
    authorize_stream_task_access,
    stream_task_events_loop,
)
from saki_api.modules.runtime.api.job import (
    JobRead,
    LoopCreateRequest,
    LoopRead,
    LoopSummaryRead,
    LoopUpdateRequest,
    SimulationComparisonRead,
    SimulationExperimentCreateRequest,
    SimulationExperimentCreateResponse,
)
from saki_api.modules.runtime.domain.loop import ALLoop
from saki_api.modules.shared.modeling import Permissions

router = APIRouter()


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    fallback = (Permissions.PROJECT_READ,) if required in {Permissions.LOOP_READ, Permissions.JOB_READ} else (
        Permissions.PROJECT_UPDATE,
    )
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required_permission=required,
        fallback_permissions=fallback,
    )


def _build_loop_read(loop) -> LoopRead:
    return build_loop_read(loop)


async def _authenticate_stream_token(websocket: WebSocket) -> uuid.UUID | None:
    return await authenticate_stream_token(websocket)


async def _authorize_stream_task_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_task_id: uuid.UUID,
) -> bool:
    return await authorize_stream_task_access(
        websocket=websocket,
        user_id=user_id,
        parsed_task_id=parsed_task_id,
    )


async def _stream_task_events_loop(
    *,
    websocket: WebSocket,
    parsed_task_id: uuid.UUID,
    cursor: int,
) -> int:
    return await stream_task_events_loop(
        websocket=websocket,
        parsed_task_id=parsed_task_id,
        cursor=cursor,
    )


@router.get("/projects/{project_id}/loops", response_model=List[LoopRead])
async def list_project_loops(
    *,
    project_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_READ,
    )
    loops = await job_service.list_loops(project_id)
    return [_build_loop_read(item) for item in loops]


@router.post("/projects/{project_id}/simulation-experiments", response_model=SimulationExperimentCreateResponse)
async def create_simulation_experiment(
    *,
    project_id: uuid.UUID,
    payload: SimulationExperimentCreateRequest,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    group_id, loops = await job_service.create_simulation_experiment(project_id=project_id, payload=payload)
    return SimulationExperimentCreateResponse(
        experiment_group_id=group_id,
        loops=[_build_loop_read(item) for item in loops],
    )


@router.post("/projects/{project_id}/loops", response_model=LoopRead)
async def create_project_loop(
    *,
    project_id: uuid.UUID,
    payload: LoopCreateRequest,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.create_loop(project_id, payload)
    return _build_loop_read(loop)


@router.get("/loops/{loop_id}", response_model=LoopRead)
async def get_loop(
    *,
    loop_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    return _build_loop_read(loop)


@router.patch("/loops/{loop_id}", response_model=LoopRead)
async def update_loop(
    *,
    loop_id: uuid.UUID,
    payload: LoopUpdateRequest,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_MANAGE,
    )
    updated = await job_service.update_loop(loop_id, payload)
    return _build_loop_read(updated)


@router.get("/loops/{loop_id}/jobs", response_model=List[JobRead])
async def list_loop_jobs(
    *,
    loop_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=1000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.JOB_READ,
    )
    jobs = await job_service.list_jobs(loop_id, limit=limit)
    return [JobRead.model_validate(item) for item in jobs]


@router.get("/loops/{loop_id}/summary", response_model=LoopSummaryRead)
async def get_loop_summary(
    *,
    loop_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    summary = await job_service.summarize_loop(loop_id)
    return LoopSummaryRead(
        loop_id=loop.id,
        status=loop.status,
        phase=loop.phase,
        jobs_total=summary.jobs_total,
        jobs_succeeded=summary.jobs_succeeded,
        tasks_total=summary.tasks_total,
        tasks_succeeded=summary.tasks_succeeded,
        metrics_latest=summary.metrics_latest,
    )


@router.get("/simulation-experiments/{group_id}/comparison", response_model=SimulationComparisonRead)
async def get_simulation_experiment_comparison(
    *,
    group_id: uuid.UUID,
    metric_name: str = Query(default="map50"),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    payload = await job_service.get_simulation_experiment_comparison(
        experiment_group_id=group_id,
        metric_name=metric_name,
    )
    loop_row = (
        await session.exec(
            select(ALLoop).where(ALLoop.experiment_group_id == group_id).limit(1)
        )
    ).first()
    if not loop_row:
        raise ForbiddenAppException("Simulation experiment not found")
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop_row.project_id,
        required=Permissions.LOOP_READ,
    )
    return payload


@router.websocket("/tasks/{task_id}/events/ws")
@router.websocket("/steps/{task_id}/events/ws")
async def stream_task_events(
    websocket: WebSocket,
    task_id: str,
    after_seq: int = 0,
):
    user_id = await _authenticate_stream_token(websocket)
    if user_id is None:
        return

    try:
        parsed_task_id = uuid.UUID(task_id)
    except Exception:
        await websocket.close(code=1008, reason="invalid task_id")
        return

    authorized = await _authorize_stream_task_access(
        websocket=websocket,
        user_id=user_id,
        parsed_task_id=parsed_task_id,
    )
    if not authorized:
        return

    await websocket.accept()
    cursor = max(0, after_seq)
    try:
        cursor = await _stream_task_events_loop(
            websocket=websocket,
            parsed_task_id=parsed_task_id,
            cursor=cursor,
        )
    except WebSocketDisconnect:
        logger.debug("task event stream disconnected task_id={} after_seq={}", parsed_task_id, cursor)
        return
    except Exception:
        logger.exception("task event stream failed task_id={} after_seq={}", parsed_task_id, cursor)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1011, reason="internal error")
        return
