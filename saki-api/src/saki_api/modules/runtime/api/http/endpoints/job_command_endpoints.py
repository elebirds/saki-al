"""Round/step command endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, JobServiceDep
from saki_api.core.exceptions import InternalServerErrorAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.job import JobCommandResponse, JobCreateRequest, JobRead, TaskCommandResponse
from saki_api.modules.shared.modeling import Permissions
from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus

router = APIRouter()


async def _trigger_dispatch(dispatcher_admin_client: DispatcherAdminClientDep) -> None:
    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")
    try:
        await dispatcher_admin_client.trigger_dispatch()
    except Exception as exc:
        logger.warning("dispatcher trigger_dispatch failed error={}", exc)
        raise InternalServerErrorAppException("dispatcher trigger_dispatch failed") from exc


@router.post("/loops/{loop_id}/rounds", response_model=JobRead)
async def create_round(
    *,
    loop_id: uuid.UUID,
    payload: JobCreateRequest,
    job_service: JobServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
    )
    round_item = await job_service.create_job_for_loop(loop_id, payload)
    await _trigger_dispatch(dispatcher_admin_client)
    return JobRead.model_validate(round_item)


@router.post("/rounds/{round_id}:stop", response_model=JobCommandResponse)
async def stop_round(
    *,
    round_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    job_service: JobServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await job_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
    )

    if round_item.state in {
        RoundStatus.COMPLETED,
        RoundStatus.FAILED,
        RoundStatus.CANCELLED,
    }:
        return JobCommandResponse(
            request_id=str(uuid.uuid4()),
            round_id=round_id,
            status=round_item.state.value,
        )

    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")
    try:
        response = await dispatcher_admin_client.stop_round(str(round_id), reason=reason)
        status = str(response.status or "").strip().lower() or "accepted"
        return JobCommandResponse(
            request_id=str(response.request_id or response.command_id or uuid.uuid4()),
            round_id=round_id,
            status="stopping" if status == "accepted" else status,
        )
    except Exception as exc:
        logger.warning("dispatcher stop_round failed round_id={} error={}", round_id, exc)
        raise InternalServerErrorAppException("dispatcher stop_round failed") from exc


@router.post("/steps/{step_id}:stop", response_model=TaskCommandResponse)
async def stop_step(
    *,
    step_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    job_service: JobServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
    )

    if step.state in {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED, StepStatus.SKIPPED}:
        return TaskCommandResponse(request_id=str(uuid.uuid4()), step_id=step_id, status=step.state.value)

    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")
    try:
        response = await dispatcher_admin_client.stop_step(str(step_id), reason=reason)
        status = str(response.status or "").strip().lower() or "accepted"
        return TaskCommandResponse(
            request_id=str(response.request_id or response.command_id or uuid.uuid4()),
            step_id=step_id,
            status="stopping" if status == "accepted" else status,
        )
    except Exception as exc:
        logger.warning("dispatcher stop_step failed step_id={} error={}", step_id, exc)
        raise InternalServerErrorAppException("dispatcher stop_step failed") from exc
