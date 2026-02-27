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
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.runtime.api.http.support.loop_read_builder import build_loop_read
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import (
    LoopAnnotationGapsResponse,
    LoopContinueResponse,
    LoopConfirmResponse,
    LoopRead,
    LoopSnapshotRead,
    LoopStageResponse,
    RoundPredictionCleanupResponse,
    SnapshotInitRequest,
    SnapshotMutationResponse,
    SnapshotUpdateRequest,
    SnapshotVersionRead,
    SnapshotVersionSummaryRead,
)
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.shared.modeling.enums import LoopMode, SnapshotPartition

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
        round_id: uuid.UUID | None = None,
        reason: str = "",
        use_latest_inputs: bool = True,
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
        if command == "retry_round":
            if not round_id:
                raise BadRequestAppException("round_id is required for retry_round")
            await dispatcher_admin_client.retry_round(
                str(round_id),
                reason=reason,
                use_latest_inputs=use_latest_inputs,
            )
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


@router.post("/loops/{loop_id}:continue", response_model=LoopContinueResponse)
async def continue_loop(
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

    stage_payload = await runtime_service.get_loop_stage(loop_id=loop_id)
    # BUGFIX(2026-02-27): release DB row lock before dispatcher RPC.
    # get_loop_stage writes loop.stage/stage_meta; without this commit, the same request
    # can hold loop row lock while dispatcher needs FOR UPDATE on loop, causing 5s timeout.
    await session.commit()
    actions = list(stage_payload.get("actions") or [])
    primary_action = stage_payload.get("primary_action") or {}
    executed_action: str | None = None
    message_text = "no actionable transition for current stage"

    action_key = str(primary_action.get("key") or "").strip().lower()
    action_payload = primary_action.get("payload") if isinstance(primary_action.get("payload"), dict) else {}
    if not action_key:
        for item in actions:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip().lower()
            runnable = bool(item.get("runnable", True))
            if key and runnable:
                action_key = key
                action_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                break

    if action_key == "start":
        await _dispatch_loop_command(
            command="start",
            loop_id=loop_id,
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = "start"
        message_text = "start dispatched"
    elif action_key == "confirm":
        await _dispatch_loop_command(
            command="confirm",
            loop_id=loop_id,
            force=force,
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = "confirm"
        message_text = "confirm dispatched"
    elif action_key == "retry_round":
        retry_round_raw = action_payload.get("round_id") or stage_payload.get("stage_meta", {}).get("retry_round_id")
        retry_round_id = uuid.UUID(str(retry_round_raw)) if retry_round_raw else None
        if retry_round_id is None:
            raise BadRequestAppException("retry_round action missing round_id")
        await _dispatch_loop_command(
            command="retry_round",
            loop_id=loop_id,
            round_id=retry_round_id,
            reason="continue retry latest failed round",
            use_latest_inputs=True,
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = "retry_round"
        message_text = "retry_round dispatched"
    elif action_key == "snapshot_init":
        message_text = "snapshot initialization required"
    elif action_key == "view_annotation_gaps":
        branch = await BranchRepository(session).get_by_id(loop.branch_id)
        branch_name = branch.name if branch else str(loop.branch_id)
        gaps_payload = await runtime_service.get_loop_annotation_gaps(loop_id=loop_id)
        critical_missing = 0
        for bucket in gaps_payload.get("buckets") or []:
            partition = bucket.get("partition")
            partition_value = str(partition.value if hasattr(partition, "value") else partition)
            if partition_value in {
                SnapshotPartition.TRAIN_SEED.value,
                SnapshotPartition.VAL_ANCHOR.value,
                SnapshotPartition.TEST_ANCHOR.value,
            }:
                critical_missing += int(bucket.get("missing_count") or 0)
        head_commit_id = gaps_payload.get("commit_id")
        message_text = (
            f"annotation gaps must be resolved before continue "
            f"(branch={branch_name}, head_commit={head_commit_id}, missing={critical_missing})"
        )
    elif action_key == "annotate":
        message_text = "more annotations are required before continue"

    stage_payload = await runtime_service.get_loop_stage(loop_id=loop_id)
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return LoopContinueResponse(
        loop_id=loop.id,
        stage=stage_payload["stage"],
        stage_meta=stage_payload.get("stage_meta") or {},
        primary_action=stage_payload.get("primary_action"),
        actions=stage_payload.get("actions") or [],
        executed_action=executed_action,
        message=message_text,
        phase=loop.phase,
        state=loop.status,
    )


@router.post("/loops/{loop_id}/snapshot:init", response_model=SnapshotMutationResponse)
async def init_loop_snapshot(
    *,
    loop_id: uuid.UUID,
    payload: SnapshotInitRequest,
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
    result = await runtime_service.init_loop_snapshot(
        loop_id=loop_id,
        payload=payload.model_dump(exclude_none=True),
        actor_user_id=current_user_id,
    )
    return SnapshotMutationResponse(**result)


@router.post("/loops/{loop_id}/snapshot:update", response_model=SnapshotMutationResponse)
async def update_loop_snapshot(
    *,
    loop_id: uuid.UUID,
    payload: SnapshotUpdateRequest,
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
    result = await runtime_service.update_loop_snapshot(
        loop_id=loop_id,
        payload=payload.model_dump(exclude_none=True),
        actor_user_id=current_user_id,
    )
    return SnapshotMutationResponse(**result)


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
