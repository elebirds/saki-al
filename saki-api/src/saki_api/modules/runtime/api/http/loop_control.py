"""Loop control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, RuntimeServiceDep
from saki_api.core.exceptions import BadRequestAppException, InternalServerErrorAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import (
    LoopActionRequest,
    LoopActionResponse,
    LoopActionSpec,
    LoopAnnotationGapsResponse,
    LoopSnapshotRead,
    LoopGateResponse,
    RoundPredictionCleanupResponse,
    SnapshotVersionRead,
    SnapshotVersionSummaryRead,
)
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.shared.modeling.enums import LoopActionKey

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


async def _dispatch_loop_command(
    *,
    command: str,
    loop_id: uuid.UUID,
    round_id: uuid.UUID | None = None,
    reason: str = "",
    force: bool = False,
    dispatcher_admin_client: DispatcherAdminClientDep,
) -> object:
    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin is not configured")

    loop_id_text = str(loop_id)
    try:
        if command == "start":
            return await dispatcher_admin_client.start_loop(loop_id_text)
        if command == "pause":
            return await dispatcher_admin_client.pause_loop(loop_id_text)
        if command == "resume":
            return await dispatcher_admin_client.resume_loop(loop_id_text)
        if command == "stop":
            return await dispatcher_admin_client.stop_loop(loop_id_text)
        if command == "confirm":
            return await dispatcher_admin_client.confirm_loop(loop_id_text, force=force)
        if command == "start_next_round":
            return await dispatcher_admin_client.start_next_round(loop_id_text)
        if command == "retry_round":
            if not round_id:
                raise BadRequestAppException("round_id is required for retry_round")
            return await dispatcher_admin_client.retry_round(
                str(round_id),
                reason=reason,
            )
        raise BadRequestAppException(f"unsupported dispatcher command: {command}")
    except Exception as exc:
        logger.warning("dispatcher loop command failed command={} loop_id={} error={}", command, loop_id, exc)
        raise InternalServerErrorAppException("dispatcher loop command failed") from exc


@router.post("/loops/{loop_id}:act", response_model=LoopActionResponse)
async def act_loop(
    *,
    loop_id: uuid.UUID,
    payload: LoopActionRequest,
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

    _decision, action_key, matched = await runtime_service.resolve_loop_action_request(
        loop_id=loop_id,
        requested_action=(payload.action.value if payload.action else None),
        decision_token=payload.decision_token,
    )
    action_payload = {}
    if isinstance(matched.get("payload"), dict):
        action_payload.update(matched["payload"])
    if payload.payload:
        action_payload.update(payload.payload)

    executed_action: LoopActionKey | None = None
    command_id: str | None = None
    message_text = f"{action_key} executed"

    if action_key == LoopActionKey.SNAPSHOT_INIT.value:
        result = await runtime_service.init_loop_snapshot(
            loop_id=loop_id,
            payload=action_payload,
            actor_user_id=current_user_id,
        )
        executed_action = LoopActionKey.SNAPSHOT_INIT
        message_text = (
            f"snapshot initialized: v{int(result.get('version_index') or 0)} "
            f"sample_count={int(result.get('sample_count') or 0)}"
        )
    elif action_key == LoopActionKey.SNAPSHOT_UPDATE.value:
        result = await runtime_service.update_loop_snapshot(
            loop_id=loop_id,
            payload=action_payload,
            actor_user_id=current_user_id,
        )
        executed_action = LoopActionKey.SNAPSHOT_UPDATE
        message_text = (
            f"snapshot updated: v{int(result.get('version_index') or 0)} "
            f"sample_count={int(result.get('sample_count') or 0)}"
        )
    elif action_key == LoopActionKey.RETRY_ROUND.value:
        retry_round_raw = action_payload.get("round_id")
        retry_round_id = uuid.UUID(str(retry_round_raw)) if retry_round_raw else None
        if retry_round_id is None:
            raise BadRequestAppException("retry_round action missing round_id")
        response = await _dispatch_loop_command(
            command="retry_round",
            loop_id=loop_id,
            round_id=retry_round_id,
            reason=str(action_payload.get("reason") or "act retry latest failed round"),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey.RETRY_ROUND
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or "retry_round dispatched")
    elif action_key in {
        LoopActionKey.START.value,
        LoopActionKey.START_NEXT_ROUND.value,
        LoopActionKey.PAUSE.value,
        LoopActionKey.RESUME.value,
        LoopActionKey.STOP.value,
        LoopActionKey.CONFIRM.value,
    }:
        response = await _dispatch_loop_command(
            command=action_key,
            loop_id=loop_id,
            force=bool(payload.force),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey(action_key)
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or f"{action_key} dispatched")
    else:
        raise BadRequestAppException(f"unsupported action: {action_key}")

    gate_payload = await runtime_service.get_loop_gate(loop_id=loop_id)
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return LoopActionResponse(
        loop_id=loop.id,
        executed_action=executed_action,
        command_id=command_id,
        message=message_text,
        gate=gate_payload["gate"],
        gate_meta=gate_payload.get("gate_meta") or {},
        primary_action=LoopActionSpec.model_validate(gate_payload.get("primary_action"))
        if gate_payload.get("primary_action")
        else None,
        actions=[LoopActionSpec.model_validate(item) for item in gate_payload.get("actions") or []],
        decision_token=str(gate_payload.get("decision_token") or ""),
        blocking_reasons=list(gate_payload.get("blocking_reasons") or []),
        phase=loop.phase,
        lifecycle=loop.lifecycle,
    )


@router.get("/loops/{loop_id}/snapshot", response_model=LoopSnapshotRead)
async def get_loop_snapshot(
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
    payload = await runtime_service.get_loop_snapshot(loop_id=loop_id)
    active = payload.get("active")
    history = payload.get("history") or []
    return LoopSnapshotRead(
        loop_id=payload["loop_id"],
        active_snapshot_version_id=payload.get("active_snapshot_version_id"),
        active=SnapshotVersionRead.model_validate(active, from_attributes=True) if active else None,
        history=[SnapshotVersionSummaryRead.model_validate(item, from_attributes=True) for item in history],
        frozen_partition_counts=payload.get("frozen_partition_counts") or {},
        virtual_visibility_counts=payload.get("virtual_visibility_counts") or {},
        effective_split_counts=payload.get("effective_split_counts") or {},
    )


@router.get("/loops/{loop_id}/gate", response_model=LoopGateResponse)
async def get_loop_gate(
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
    payload = await runtime_service.get_loop_gate(loop_id=loop_id)
    return LoopGateResponse(**payload)


@router.get("/loops/{loop_id}/annotation-gaps", response_model=LoopAnnotationGapsResponse)
async def get_loop_annotation_gaps(
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
    payload = await runtime_service.get_loop_annotation_gaps(loop_id=loop_id)
    return LoopAnnotationGapsResponse(**payload)


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
