"""Loop control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.service_deps import JobServiceDep
from saki_api.core.exceptions import BadRequestAppException, ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.models import Permissions, ResourceType
from saki_api.models.enums import ALLoopMode, ALLoopStatus
from saki_api.schemas.l3.job import LoopConfirmResponse, LoopRead
from saki_api.services.loop_config import extract_model_request_config, extract_simulation_config
from saki_api.services.loop_orchestrator import loop_orchestrator

router = APIRouter()


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    checker = PermissionChecker(session)
    allowed = await checker.check(
        user_id=current_user_id,
        permission=required,
        resource_type=ResourceType.PROJECT,
        resource_id=str(project_id),
    )
    if not allowed:
        fallback = Permissions.PROJECT_UPDATE if required == Permissions.LOOP_MANAGE else Permissions.PROJECT_READ
        allowed = await checker.check(
            user_id=current_user_id,
            permission=fallback,
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
        )
    if not allowed:
        raise ForbiddenAppException(f"Permission denied: {required}")


def _build_loop_read(loop) -> LoopRead:
    row = LoopRead.model_validate(loop, from_attributes=True)
    return row.model_copy(
        update={
            "model_request_config": extract_model_request_config(getattr(loop, "global_config", {})),
            "simulation_config": extract_simulation_config(getattr(loop, "global_config", {})),
        }
    )


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
    if loop.status == ALLoopStatus.COMPLETED:
        raise BadRequestAppException("Completed loop cannot be started")

    loop.status = ALLoopStatus.RUNNING
    session.add(loop)
    await session.commit()
    await session.refresh(loop)
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
    loop.status = ALLoopStatus.PAUSED
    session.add(loop)
    await session.commit()
    await session.refresh(loop)
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
    if loop.status in {ALLoopStatus.STOPPED, ALLoopStatus.COMPLETED}:
        raise BadRequestAppException(f"Loop in status {loop.status} cannot be resumed")
    loop.status = ALLoopStatus.RUNNING
    session.add(loop)
    await session.commit()
    await session.refresh(loop)
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
    loop.status = ALLoopStatus.STOPPED
    session.add(loop)
    await session.commit()
    await session.refresh(loop)
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
