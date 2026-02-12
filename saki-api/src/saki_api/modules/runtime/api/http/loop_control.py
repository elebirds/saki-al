"""Loop control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import JobServiceDep
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.job import LoopConfirmResponse, LoopRead
from saki_api.modules.runtime.service.orchestration.loop_orchestrator_service import (
    loop_orchestrator,
)
from saki_api.modules.shared.modeling import Permissions
from saki_api.modules.shared.modeling.enums import ALLoopMode

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


@router.post("/loops/{loop_id}:start", response_model=LoopRead)
async def start_loop(
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
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.start_loop(loop_id)
    await loop_orchestrator.tick_once()
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:pause", response_model=LoopRead)
async def pause_loop(
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
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.pause_loop(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:resume", response_model=LoopRead)
async def resume_loop(
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
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.resume_loop(loop_id)
    await loop_orchestrator.tick_once()
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:stop", response_model=LoopRead)
async def stop_loop(
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
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.stop_loop(loop_id)
    return _build_loop_read(loop)


@router.post("/loops/{loop_id}:confirm", response_model=LoopConfirmResponse)
async def confirm_loop(
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
        required=Permissions.LOOP_MANAGE,
    )
    if loop.mode != ALLoopMode.MANUAL:
        raise BadRequestAppException("confirm is only available for manual mode")

    loop = await job_service.confirm_loop_step(loop_id)
    await loop_orchestrator.tick_once()
    return LoopConfirmResponse(loop_id=loop.id, phase=loop.phase, status=loop.status)
