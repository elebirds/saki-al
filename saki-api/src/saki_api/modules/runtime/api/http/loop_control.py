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
    LoopSnapshotRead,
    LoopGateResponse,
    PredictionSetApplyRequest,
    PredictionSetApplyResponse,
    PredictionSetDetailRead,
    PredictionSetGenerateRequest,
    PredictionSetRead,
    PredictionTaskRead,
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


def _to_prediction_set_read(row, *, task_step=None) -> PredictionSetRead:
    return PredictionSetRead(
        id=row.id,
        project_id=row.project_id,
        loop_id=row.loop_id,
        plugin_id=str(row.plugin_id or ""),
        source_round_id=row.source_round_id,
        source_step_id=row.source_step_id,
        model_id=row.model_id,
        base_commit_id=row.base_commit_id,
        scope_type=str(row.scope_type or ""),
        scope_payload=dict(row.scope_payload or {}),
        status=str(row.status or ""),
        total_items=int(row.total_items or 0),
        params=dict(row.params or {}),
        last_error=row.last_error,
        task_step_id=getattr(task_step, "id", None),
        task_step_state=getattr(task_step, "state", None),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_prediction_task_read(row, *, task_step=None) -> PredictionTaskRead:
    return PredictionTaskRead(**_to_prediction_set_read(row, task_step=task_step).model_dump())


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
        primary_view=payload.get("primary_view") or {},
        advanced_view=payload.get("advanced_view") or {},
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


@router.post("/projects/{project_id}/prediction-sets:generate", response_model=PredictionSetRead)
async def generate_prediction_set(
    *,
    project_id: uuid.UUID,
    payload: PredictionSetGenerateRequest,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    result = await runtime_service.generate_prediction_set(
        project_id=project_id,
        payload=payload.model_dump(exclude_none=True),
        actor_user_id=current_user_id,
    )
    task_step_id = result.source_step_id
    if task_step_id is not None and dispatcher_admin_client.enabled:
        try:
            await dispatcher_admin_client.dispatch_step(str(task_step_id))
        except Exception as exc:
            logger.warning("dispatch prediction task failed task_step_id={} error={}", task_step_id, exc)
            await runtime_service.prediction_set_repo.update(
                result.id,
                {"last_error": f"dispatch failed: {exc}"},
            )
    settled = await runtime_service.get_prediction_task(task_id=result.id)
    settled_step = await runtime_service.step_repo.get_by_id(settled.source_step_id) if settled.source_step_id else None
    return _to_prediction_set_read(settled, task_step=settled_step)


@router.get("/projects/{project_id}/prediction-sets", response_model=list[PredictionSetRead])
async def list_prediction_sets(
    *,
    project_id: uuid.UUID,
    limit: int = 100,
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
    rows = await runtime_service.list_prediction_sets(project_id=project_id, limit=limit)
    step_ids = [row.source_step_id for row in rows if row.source_step_id is not None]
    steps = await runtime_service.step_repo.get_by_ids(step_ids)
    step_by_id = {item.id: item for item in steps}
    return [_to_prediction_set_read(row, task_step=step_by_id.get(row.source_step_id)) for row in rows]


@router.get("/projects/{project_id}/prediction-tasks", response_model=list[PredictionTaskRead])
async def list_prediction_tasks(
    *,
    project_id: uuid.UUID,
    limit: int = 100,
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
    rows = await runtime_service.list_prediction_tasks(project_id=project_id, limit=limit)
    step_ids = [row.source_step_id for row in rows if row.source_step_id is not None]
    steps = await runtime_service.step_repo.get_by_ids(step_ids)
    step_by_id = {item.id: item for item in steps}
    return [_to_prediction_task_read(row, task_step=step_by_id.get(row.source_step_id)) for row in rows]


@router.get("/prediction-tasks/{task_id}", response_model=PredictionTaskRead)
async def get_prediction_task(
    *,
    task_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    row = await runtime_service.get_prediction_task(task_id=task_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=row.project_id,
        required=Permissions.LOOP_READ,
    )
    step = await runtime_service.step_repo.get_by_id(row.source_step_id) if row.source_step_id else None
    return _to_prediction_task_read(row, task_step=step)


@router.get("/prediction-sets/{prediction_set_id}", response_model=PredictionSetDetailRead)
async def get_prediction_set_detail(
    *,
    prediction_set_id: uuid.UUID,
    item_limit: int = 2000,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    prediction_set, items = await runtime_service.get_prediction_set_detail(
        prediction_set_id=prediction_set_id,
        item_limit=item_limit,
    )
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=prediction_set.project_id,
        required=Permissions.LOOP_READ,
    )
    return PredictionSetDetailRead(
        prediction_set=_to_prediction_set_read(
            prediction_set,
            task_step=(
                await runtime_service.step_repo.get_by_id(prediction_set.source_step_id)
                if prediction_set.source_step_id
                else None
            ),
        ),
        items=[
            {
                "sample_id": row.sample_id,
                "rank": int(row.rank or 0),
                "score": float(row.score or 0.0),
                "label_id": row.label_id,
                "geometry": dict(row.geometry or {}),
                "attrs": dict(row.attrs or {}),
                "confidence": float(row.confidence or 0.0),
                "meta": dict(row.meta or {}),
            }
            for row in items
        ],
    )


@router.post("/prediction-sets/{prediction_set_id}:apply", response_model=PredictionSetApplyResponse)
async def apply_prediction_set(
    *,
    prediction_set_id: uuid.UUID,
    payload: PredictionSetApplyRequest,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    prediction_set = await runtime_service.prediction_set_repo.get_by_id_or_raise(prediction_set_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=prediction_set.project_id,
        required=Permissions.LOOP_MANAGE,
    )
    result = await runtime_service.apply_prediction_set(
        prediction_set_id=prediction_set_id,
        actor_user_id=current_user_id,
        branch_name=payload.branch_name,
        dry_run=bool(payload.dry_run),
    )
    return PredictionSetApplyResponse(
        prediction_set_id=result["prediction_set_id"],
        applied_count=int(result.get("applied_count", 0)),
        status=str(result.get("status") or "ready"),
    )


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
