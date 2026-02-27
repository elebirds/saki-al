"""Loop control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
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
    LoopContinueResponse,
    LoopConfirmResponse,
    LoopRead,
    LoopSnapshotRead,
    LoopStageResponse,
    RoundPredictionCleanupResponse,
    SnapshotMutationResponse,
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
        use_latest_inputs: bool = True,
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
        if command == "retry_round":
            if not round_id:
                raise BadRequestAppException("round_id is required for retry_round")
            return await dispatcher_admin_client.retry_round(
                str(round_id),
                reason=reason,
                use_latest_inputs=use_latest_inputs,
            )
        raise BadRequestAppException(f"unsupported dispatcher command: {command}")
    except Exception as exc:
        logger.warning("dispatcher loop command failed command={} loop_id={} error={}", command, loop_id, exc)
        raise InternalServerErrorAppException("dispatcher loop command failed") from exc


def _deprecated_action_error(*, endpoint: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "message": f"{endpoint} has been removed; use POST /api/v1/loops/{{loop_id}}:act",
            "replacement": "/api/v1/loops/{loop_id}:act",
        },
    )


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
            use_latest_inputs=bool(action_payload.get("use_latest_inputs", True)),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey.RETRY_ROUND
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or "retry_round dispatched")
    elif action_key in {
        LoopActionKey.START.value,
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

    stage_payload = await runtime_service.get_loop_stage(loop_id=loop_id)
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return LoopActionResponse(
        loop_id=loop.id,
        executed_action=executed_action,
        command_id=command_id,
        message=message_text,
        stage=stage_payload["stage"],
        stage_meta=stage_payload.get("stage_meta") or {},
        primary_action=LoopActionSpec.model_validate(stage_payload.get("primary_action"))
        if stage_payload.get("primary_action")
        else None,
        actions=[LoopActionSpec.model_validate(item) for item in stage_payload.get("actions") or []],
        decision_token=str(stage_payload.get("decision_token") or ""),
        blocking_reasons=list(stage_payload.get("blocking_reasons") or []),
        phase=loop.phase,
        state=loop.status,
    )


@router.post("/loops/{loop_id}:start", response_model=LoopRead)
async def start_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:start")


@router.post("/loops/{loop_id}:pause", response_model=LoopRead)
async def pause_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:pause")


@router.post("/loops/{loop_id}:resume", response_model=LoopRead)
async def resume_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:resume")


@router.post("/loops/{loop_id}:stop", response_model=LoopRead)
async def stop_loop(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:stop")


@router.post("/loops/{loop_id}:confirm", response_model=LoopConfirmResponse)
async def confirm_loop(
    *,
    loop_id: uuid.UUID,
    force: bool = False,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, force, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:confirm")


@router.post("/loops/{loop_id}:continue", response_model=LoopContinueResponse)
async def continue_loop(
    *,
    loop_id: uuid.UUID,
    force: bool = False,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, force, runtime_service, dispatcher_admin_client, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}:continue")


@router.post("/loops/{loop_id}/snapshot:init", response_model=SnapshotMutationResponse)
async def init_loop_snapshot(
    *,
    loop_id: uuid.UUID,
    payload: dict | None = None,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, payload, runtime_service, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}/snapshot:init")


@router.post("/loops/{loop_id}/snapshot:update", response_model=SnapshotMutationResponse)
async def update_loop_snapshot(
    *,
    loop_id: uuid.UUID,
    payload: dict | None = None,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    del loop_id, payload, runtime_service, session, current_user_id
    _deprecated_action_error(endpoint="POST /loops/{loop_id}/snapshot:update")


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
        partition_counts=payload.get("partition_counts") or {},
    )


@router.get("/loops/{loop_id}/stage", response_model=LoopStageResponse)
async def get_loop_stage(
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
    payload = await runtime_service.get_loop_stage(loop_id=loop_id)
    return LoopStageResponse(**payload)


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
