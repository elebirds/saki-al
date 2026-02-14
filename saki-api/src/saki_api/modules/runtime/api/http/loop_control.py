"""Loop control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, RuntimeServiceDep
from saki_api.core.exceptions import BadRequestAppException, InternalServerErrorAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import LoopConfirmResponse, LoopRead, RoundPredictionCleanupResponse
from saki_api.modules.shared.modeling import Permissions
from saki_api.modules.shared.modeling.enums import LoopMode

router = APIRouter()


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    fallback = (Permissions.PROJECT_UPDATE,) if required == Permissions.LOOP_MANAGE else (Permissions.PROJECT_READ,)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required_permission=required,
        fallback_permissions=fallback,
    )


def _build_loop_read(loop) -> LoopRead:
    return build_loop_read(loop)


async def _dispatch_loop_command(
        *,
        command: str,
        loop_id: uuid.UUID,
        force: bool = False,
        dispatcher_admin_client: DispatcherAdminClientDep,
) -> None:
    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")

    loop_id_text = str(loop_id)
    try:
        if command == "start":
            await dispatcher_admin_client.start_loop(loop_id_text)
            return
        if command == "pause":
            await dispatcher_admin_client.pause_loop(loop_id_text)
            return
        if command == "resume":
            await dispatcher_admin_client.resume_loop(loop_id_text)
            return
        if command == "stop":
            await dispatcher_admin_client.stop_loop(loop_id_text)
            return
        if command == "confirm":
            await dispatcher_admin_client.confirm_loop(loop_id_text, force=force)
            return
    except Exception as exc:
        logger.warning("dispatcher loop command failed command={} loop_id={} error={}", command, loop_id, exc)
        raise InternalServerErrorAppException("dispatcher loop command failed") from exc


@router.post("/loops/{loop_id}:start", response_model=LoopRead)
async def start_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
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
    await _dispatch_loop_command(
        command="start",
        loop_id=loop_id,
        dispatcher_admin_client=dispatcher_admin_client,
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:pause", response_model=LoopRead)
async def pause_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
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
    await _dispatch_loop_command(
        command="pause",
        loop_id=loop_id,
        dispatcher_admin_client=dispatcher_admin_client,
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:resume", response_model=LoopRead)
async def resume_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
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
    await _dispatch_loop_command(
        command="resume",
        loop_id=loop_id,
        dispatcher_admin_client=dispatcher_admin_client,
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:stop", response_model=LoopRead)
async def stop_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
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
    await _dispatch_loop_command(
        command="stop",
        loop_id=loop_id,
        dispatcher_admin_client=dispatcher_admin_client,
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:confirm", response_model=LoopConfirmResponse)
async def confirm_loop(
    *,
    loop_id: uuid.UUID,
    force: bool = Query(default=False),
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
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
    if loop.mode == LoopMode.MANUAL:
        raise BadRequestAppException("manual mode is single-run and does not require confirm")
    if loop.mode == LoopMode.SIMULATION:
        raise BadRequestAppException("simulation mode does not require confirm")

    await _dispatch_loop_command(
        command="confirm",
        loop_id=loop_id,
        force=force,
        dispatcher_admin_client=dispatcher_admin_client,
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return LoopConfirmResponse(loop_id=loop.id, phase=loop.phase, state=loop.status)


@router.post("/loops/{loop_id}/rounds/{round_index}:cleanup-predictions", response_model=RoundPredictionCleanupResponse)
async def cleanup_round_predictions(
    *,
    loop_id: uuid.UUID,
    round_index: int,
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
    stats = await runtime_service.cleanup_round_predictions(
        loop_id=loop_id,
        round_index=round_index,
        actor_user_id=current_user_id,
    )
    return RoundPredictionCleanupResponse(
        loop_id=loop_id,
        round_index=round_index,
        score_steps=int(stats.get("score_steps", 0)),
        candidate_rows_deleted=int(stats.get("candidate_rows_deleted", 0)),
        event_rows_deleted=int(stats.get("event_rows_deleted", 0)),
        metric_rows_deleted=int(stats.get("metric_rows_deleted", 0)),
    )
