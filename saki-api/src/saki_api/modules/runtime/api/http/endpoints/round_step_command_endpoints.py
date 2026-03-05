"""Round/step command endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, RuntimeServiceDep
from saki_api.core.exceptions import InternalServerErrorAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import (
    RoundSelectionApplyRequest,
    RoundSelectionApplyResponse,
    RoundCommandResponse,
    StepCommandResponse,
)
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus

router = APIRouter()


@router.post("/rounds/{round_id}/selection:apply", response_model=RoundSelectionApplyResponse)
async def apply_round_selection(
    *,
    round_id: uuid.UUID,
    payload: RoundSelectionApplyRequest,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await runtime_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_MANAGE,
    )
    result = await runtime_service.apply_round_selection_override(
        round_id=round_id,
        include_sample_ids=payload.include_sample_ids,
        exclude_sample_ids=payload.exclude_sample_ids,
        actor_user_id=current_user_id,
        reason=payload.reason,
    )
    return RoundSelectionApplyResponse(
        round_id=round_id,
        selected_count=int(result.get("selected_count") or 0),
        include_count=int(result.get("include_count") or 0),
        exclude_count=int(result.get("exclude_count") or 0),
        effective_selected=result.get("effective_selected") or [],
    )


@router.post("/rounds/{round_id}/selection:reset", response_model=RoundSelectionApplyResponse)
async def reset_round_selection(
    *,
    round_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await runtime_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_MANAGE,
    )
    result = await runtime_service.reset_round_selection_override(round_id=round_id)
    return RoundSelectionApplyResponse(
        round_id=round_id,
        selected_count=int(result.get("selected_count") or 0),
        include_count=int(result.get("include_count") or 0),
        exclude_count=int(result.get("exclude_count") or 0),
        effective_selected=result.get("effective_selected") or [],
    )


@router.post("/rounds/{round_id}:stop", response_model=RoundCommandResponse)
async def stop_round(
    *,
    round_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await runtime_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_MANAGE,
    )

    if round_item.state in {
        RoundStatus.COMPLETED,
        RoundStatus.FAILED,
        RoundStatus.CANCELLED,
    }:
        return RoundCommandResponse(
            request_id=str(uuid.uuid4()),
            round_id=round_id,
            status=round_item.state.value,
        )

    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")
    try:
        response = await dispatcher_admin_client.stop_round(str(round_id), reason=reason)
        status = str(response.status or "").strip().lower() or "accepted"
        return RoundCommandResponse(
            request_id=str(response.request_id or response.command_id or uuid.uuid4()),
            round_id=round_id,
            status="stopping" if status == "accepted" else status,
        )
    except Exception as exc:
        logger.warning("dispatcher stop_round failed round_id={} error={}", round_id, exc)
        raise InternalServerErrorAppException("dispatcher stop_round failed") from exc

@router.post("/steps/{step_id}:stop", response_model=StepCommandResponse)
async def stop_step(
    *,
    step_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_MANAGE,
    )

    if step.state in {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED, StepStatus.SKIPPED}:
        return StepCommandResponse(request_id=str(uuid.uuid4()), step_id=step_id, status=step.state.value)

    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")
    try:
        dispatch_task_id = str(getattr(step, "task_id", None) or step_id)
        response = await dispatcher_admin_client.stop_task(dispatch_task_id, reason=reason)
        status = str(response.status or "").strip().lower() or "accepted"
        return StepCommandResponse(
            request_id=str(response.request_id or response.command_id or uuid.uuid4()),
            step_id=step_id,
            status="stopping" if status == "accepted" else status,
        )
    except Exception as exc:
        logger.warning("dispatcher stop_step failed step_id={} error={}", step_id, exc)
        raise InternalServerErrorAppException("dispatcher stop_step failed") from exc
