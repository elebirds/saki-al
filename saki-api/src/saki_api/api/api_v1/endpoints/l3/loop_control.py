"""
Loop control and annotation-batch endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.service_deps import JobServiceDep, AnnotationBatchServiceDep
from saki_api.core.exceptions import ForbiddenAppException, BadRequestAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.models import Permissions, ResourceType
from saki_api.models.enums import ALLoopStatus
from saki_api.schemas.l3.job import (
    LoopRead,
    AnnotationBatchRead,
    AnnotationBatchItemRead,
)
from saki_api.services.loop_config import extract_model_request_config
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
        update={"model_request_config": extract_model_request_config(getattr(loop, "global_config", {}))}
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
    loop.is_active = True
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
    loop.is_active = True
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
    loop.is_active = False
    session.add(loop)
    await session.commit()
    await session.refresh(loop)
    return _build_loop_read(loop)


@router.get("/annotation-batches/{batch_id}", response_model=AnnotationBatchRead)
async def get_annotation_batch(
        *,
        batch_id: uuid.UUID,
        batch_service: AnnotationBatchServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    batch = await batch_service.refresh_progress(batch_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=batch.project_id,
        required=Permissions.JOB_READ,
    )
    return AnnotationBatchRead.model_validate(batch)


@router.get("/annotation-batches/{batch_id}/items", response_model=List[AnnotationBatchItemRead])
async def get_annotation_batch_items(
        *,
        batch_id: uuid.UUID,
        limit: int = Query(default=5000, ge=1, le=50000),
        batch_service: AnnotationBatchServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    batch = await batch_service.get_batch_or_raise(batch_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=batch.project_id,
        required=Permissions.JOB_READ,
    )
    items = await batch_service.list_items(batch_id=batch_id, limit=limit)
    return [AnnotationBatchItemRead.model_validate(item) for item in items]
