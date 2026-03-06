"""L3 query endpoints for Loop/Round/Step runtime."""

from __future__ import annotations

import contextlib
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocketState

from saki_api.app.deps import RuntimeServiceDep
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.http.support.round_event_stream import (
    authorize_stream_round_access,
    stream_round_events_loop,
)
from saki_api.modules.runtime.api.http.support.task_event_stream import (
    authenticate_stream_token,
    authorize_stream_task_access,
    stream_task_events_loop,
)
from saki_api.modules.runtime.api.round_step import (
    LoopCreateRequest,
    LoopRead,
    LoopSummaryRead,
    LoopUpdateRequest,
    RoundRead,
)
from saki_api.modules.access.domain.rbac import Permissions

router = APIRouter()


def _csv_to_list(raw: str | None) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if str(item).strip()]


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required_permission=required,
    )


async def _build_loop_read(runtime_service: RuntimeServiceDep, loop) -> LoopRead:
    decision = await runtime_service.get_loop_gate(loop_id=loop.id)
    return build_loop_read(
        loop=loop,
        gate=decision["gate"],
        gate_meta=decision.get("gate_meta") or {},
    )


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


async def _authorize_stream_round_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_round_id: uuid.UUID,
) -> bool:
    return await authorize_stream_round_access(
        websocket=websocket,
        user_id=user_id,
        parsed_round_id=parsed_round_id,
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


async def _stream_round_events_loop(
    *,
    websocket: WebSocket,
    parsed_round_id: uuid.UUID,
    after_cursor: str | None,
    stages: list[str] | None,
) -> str | None:
    return await stream_round_events_loop(
        websocket=websocket,
        parsed_round_id=parsed_round_id,
        after_cursor=after_cursor,
        stages=stages,
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
    return [await _build_loop_read(runtime_service, item) for item in loops]


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
    return await _build_loop_read(runtime_service, loop)


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
    return await _build_loop_read(runtime_service, loop)


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
    return await _build_loop_read(runtime_service, updated)


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
    round_ids = [item.id for item in rounds]
    steps = await runtime_service.step_repo.list_by_round_ids(round_ids) if round_ids else []
    task_metrics_by_task_id = await runtime_service._build_task_result_metrics_map(steps, strict=True)
    steps_by_round = runtime_service._group_steps_by_round(steps)
    latest_round = rounds[0] if rounds else None
    loop_phase_text = loop.phase.value
    items: list[RoundRead] = []
    loop_mode_text = loop.mode.value
    for row in rounds:
        metric_view = runtime_service.derive_round_metric_view(
            round_item=row,
            steps=steps_by_round.get(row.id, []),
            task_metrics_by_task_id=task_metrics_by_task_id,
        )
        awaiting_confirm = (
            loop_mode_text == "active_learning"
            and loop_phase_text == "al_wait_user"
            and latest_round is not None
            and latest_round.id == row.id
            and row.state.value == "completed"
            and row.confirmed_at is None
        )
        payload = RoundRead.model_validate(row).model_dump()
        payload["awaiting_confirm"] = bool(awaiting_confirm)
        payload["final_metrics"] = metric_view.final_metrics
        payload["train_final_metrics"] = metric_view.train_final_metrics
        payload["eval_final_metrics"] = metric_view.eval_final_metrics
        payload["final_metrics_source"] = metric_view.final_metrics_source
        items.append(RoundRead(**payload))
    return items


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
        lifecycle=loop.lifecycle,
        phase=loop.phase,
        rounds_total=summary.rounds_total,
        attempts_total=summary.attempts_total,
        rounds_succeeded=summary.rounds_succeeded,
        steps_total=summary.steps_total,
        steps_succeeded=summary.steps_succeeded,
        metrics_latest=summary.metrics_latest,
        metrics_latest_train=summary.metrics_latest_train,
        metrics_latest_eval=summary.metrics_latest_eval,
        metrics_latest_source=summary.metrics_latest_source,
    )


@router.websocket("/tasks/{task_id}/events/ws")
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


@router.websocket("/rounds/{round_id}/events/ws")
async def stream_round_events(
    websocket: WebSocket,
    round_id: str,
    after_cursor: str | None = None,
    stages: str | None = None,
):
    user_id = await _authenticate_stream_token(websocket)
    if user_id is None:
        return

    try:
        parsed_round_id = uuid.UUID(round_id)
    except Exception:
        await websocket.close(code=1008, reason="invalid round_id")
        return

    authorized = await _authorize_stream_round_access(
        websocket=websocket,
        user_id=user_id,
        parsed_round_id=parsed_round_id,
    )
    if not authorized:
        return

    stage_list = _csv_to_list(stages)
    await websocket.accept()
    cursor = str(after_cursor or "").strip() or None
    try:
        cursor = await _stream_round_events_loop(
            websocket=websocket,
            parsed_round_id=parsed_round_id,
            after_cursor=cursor,
            stages=stage_list,
        )
    except BadRequestAppException:
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1008, reason="invalid after_cursor")
        return
    except WebSocketDisconnect:
        logger.debug("round event stream disconnected round_id={} after_cursor={}", parsed_round_id, cursor or "")
        return
    except Exception:
        logger.exception("round event stream failed round_id={} after_cursor={}", parsed_round_id, cursor or "")
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1011, reason="internal error")
        return
