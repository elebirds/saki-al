"""L3 query endpoints for Loop/Round/Step runtime."""

from __future__ import annotations

import contextlib
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocketState

from saki_api.app.deps import RuntimeServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.http.support.step_event_stream import (
    authenticate_stream_token,
    authorize_stream_step_access,
    stream_step_events_loop,
)
from saki_api.modules.runtime.api.round_step import (
    LoopCreateRequest,
    LoopRead,
    LoopSummaryRead,
    LoopUpdateRequest,
    RoundRead,
    SimulationComparisonRead,
    SimulationExperimentCreateRequest,
    SimulationExperimentCreateResponse,
)
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.access.domain.rbac import Permissions

router = APIRouter()


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    fallback = (Permissions.PROJECT_READ,) if required in {Permissions.LOOP_READ, Permissions.ROUND_READ} else (
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


async def _authorize_stream_step_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_step_id: uuid.UUID,
) -> bool:
    return await authorize_stream_step_access(
        websocket=websocket,
        user_id=user_id,
        parsed_step_id=parsed_step_id,
    )


async def _stream_step_events_loop(
    *,
    websocket: WebSocket,
    parsed_step_id: uuid.UUID,
    cursor: int,
) -> int:
    return await stream_step_events_loop(
        websocket=websocket,
        parsed_step_id=parsed_step_id,
        cursor=cursor,
    )


@router.get("/projects/{project_id}/loops", response_model=List[LoopRead])
async def list_project_loops(
    *,
    project_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_READ,
    )
    loops = await runtime_service.list_loops(project_id)
    return [_build_loop_read(item) for item in loops]


@router.post("/projects/{project_id}/simulation-experiments", response_model=SimulationExperimentCreateResponse)
async def create_simulation_experiment(
    *,
    project_id: uuid.UUID,
    payload: SimulationExperimentCreateRequest,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    group_id, loops = await runtime_service.create_simulation_experiment(project_id=project_id, payload=payload)
    return SimulationExperimentCreateResponse(
        experiment_group_id=group_id,
        loops=[_build_loop_read(item) for item in loops],
    )


@router.post("/projects/{project_id}/loops", response_model=LoopRead)
async def create_project_loop(
    *,
    project_id: uuid.UUID,
    payload: LoopCreateRequest,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    loop = await runtime_service.create_loop(project_id, payload)
    return _build_loop_read(loop)


@router.get("/loops/{loop_id}", response_model=LoopRead)
async def get_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
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
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_MANAGE,
    )
    updated = await runtime_service.update_loop(loop_id, payload)
    return _build_loop_read(updated)


@router.get("/loops/{loop_id}/rounds", response_model=List[RoundRead])
async def list_loop_rounds(
    *,
    loop_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=1000),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.ROUND_READ,
    )
    rounds = await runtime_service.list_rounds(loop_id, limit=limit)
    return [RoundRead.model_validate(item) for item in rounds]


@router.get("/loops/{loop_id}/summary", response_model=LoopSummaryRead)
async def get_loop_summary(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    summary = await runtime_service.summarize_loop(loop_id)
    return LoopSummaryRead(
        loop_id=loop.id,
        status=loop.status,
        phase=loop.phase,
        rounds_total=summary.rounds_total,
        rounds_succeeded=summary.rounds_succeeded,
        steps_total=summary.steps_total,
        steps_succeeded=summary.steps_succeeded,
        metrics_latest=summary.metrics_latest,
    )


@router.get("/simulation-experiments/{group_id}/comparison", response_model=SimulationComparisonRead)
async def get_simulation_experiment_comparison(
    *,
    group_id: uuid.UUID,
    metric_name: str = Query(default="map50"),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    payload = await runtime_service.get_simulation_experiment_comparison(
        experiment_group_id=group_id,
        metric_name=metric_name,
    )
    loop_row = (
        await session.exec(
            select(Loop).where(Loop.experiment_group_id == group_id).limit(1)
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


@router.websocket("/steps/{step_id}/events/ws")
async def stream_step_events(
    websocket: WebSocket,
    step_id: str,
    after_seq: int = 0,
):
    user_id = await _authenticate_stream_token(websocket)
    if user_id is None:
        return

    try:
        parsed_step_id = uuid.UUID(step_id)
    except Exception:
        await websocket.close(code=1008, reason="invalid step_id")
        return

    authorized = await _authorize_stream_step_access(
        websocket=websocket,
        user_id=user_id,
        parsed_step_id=parsed_step_id,
    )
    if not authorized:
        return

    await websocket.accept()
    cursor = max(0, after_seq)
    try:
        cursor = await _stream_step_events_loop(
            websocket=websocket,
            parsed_step_id=parsed_step_id,
            cursor=cursor,
        )
    except WebSocketDisconnect:
        logger.debug("step event stream disconnected step_id={} after_seq={}", parsed_step_id, cursor)
        return
    except Exception:
        logger.exception("step event stream failed step_id={} after_seq={}", parsed_step_id, cursor)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1011, reason="internal error")
        return
