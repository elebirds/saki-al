"""Prediction/task endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, RuntimeServiceDep
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.runtime.api.http.support.loop_control_helpers import (
    ensure_loop_project_perm,
    to_prediction_read,
    to_prediction_task_read,
)
from saki_api.modules.runtime.api.round_step import (
    PredictionApplyRequest,
    PredictionApplyResponse,
    PredictionCreateRequest,
    PredictionDetailRead,
    PredictionRead,
    PredictionTaskRead,
    RoundPredictionCleanupResponse,
)

router = APIRouter()


@router.post("/projects/{project_id}/predictions", response_model=PredictionRead)
async def create_prediction(
    *,
    project_id: uuid.UUID,
    payload: PredictionCreateRequest,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    result = await runtime_service.create_prediction(
        project_id=project_id,
        payload=payload.model_dump(exclude_none=True),
        actor_user_id=current_user_id,
    )
    dispatch_task_id = result.task_id
    if dispatcher_admin_client.enabled:
        try:
            await dispatcher_admin_client.dispatch_task(str(dispatch_task_id))
        except Exception as exc:
            logger.warning("dispatch prediction task failed task_id={} error={}", dispatch_task_id, exc)
            await runtime_service.prediction_repo.update(
                result.id,
                {"last_error": f"dispatch failed: {exc}"},
            )
    settled = await runtime_service.get_prediction_task(task_id=result.task_id)
    task = await runtime_service.task_repo.get_by_id(settled.task_id)
    return to_prediction_read(settled, task=task)


@router.get("/projects/{project_id}/predictions", response_model=list[PredictionRead])
async def list_predictions(
    *,
    project_id: uuid.UUID,
    limit: int = 100,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_READ,
    )
    rows = await runtime_service.list_predictions(project_id=project_id, limit=limit)
    task_ids = [row.task_id for row in rows if getattr(row, "task_id", None) is not None]
    tasks = await runtime_service.task_repo.get_by_ids(task_ids)
    task_by_id = {item.id: item for item in tasks}
    return [
        to_prediction_read(
            row,
            task=task_by_id.get(getattr(row, "task_id", None)),
        )
        for row in rows
    ]


@router.get("/projects/{project_id}/prediction-tasks", response_model=list[PredictionTaskRead])
async def list_prediction_tasks(
    *,
    project_id: uuid.UUID,
    limit: int = 100,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_READ,
    )
    rows = await runtime_service.list_prediction_tasks(project_id=project_id, limit=limit)
    task_ids = [row.task_id for row in rows if getattr(row, "task_id", None) is not None]
    tasks = await runtime_service.task_repo.get_by_ids(task_ids)
    task_by_id = {item.id: item for item in tasks}
    return [
        to_prediction_task_read(
            row,
            task=task_by_id.get(getattr(row, "task_id", None)),
        )
        for row in rows
    ]


@router.get("/prediction-tasks/{task_id}", response_model=PredictionTaskRead)
async def get_prediction_task(
    *,
    task_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    row = await runtime_service.get_prediction_task(task_id=task_id)
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=row.project_id,
        required=Permissions.LOOP_READ,
    )
    task = await runtime_service.task_repo.get_by_id(row.task_id) if getattr(row, "task_id", None) else None
    return to_prediction_task_read(row, task=task)


@router.get("/predictions/{prediction_id}", response_model=PredictionDetailRead)
async def get_prediction_detail(
    *,
    prediction_id: uuid.UUID,
    item_limit: int = 2000,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    prediction, items = await runtime_service.get_prediction_detail(
        prediction_id=prediction_id,
        item_limit=item_limit,
    )
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=prediction.project_id,
        required=Permissions.LOOP_READ,
    )
    return PredictionDetailRead(
        prediction=to_prediction_read(
            prediction,
            task=(await runtime_service.task_repo.get_by_id(prediction.task_id) if prediction.task_id else None),
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


@router.post("/predictions/{prediction_id}:apply", response_model=PredictionApplyResponse)
async def apply_prediction(
    *,
    prediction_id: uuid.UUID,
    payload: PredictionApplyRequest,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    prediction = await runtime_service.prediction_repo.get_by_id_or_raise(prediction_id)
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=prediction.project_id,
        required=Permissions.LOOP_MANAGE,
    )
    result = await runtime_service.apply_prediction(
        prediction_id=prediction_id,
        actor_user_id=current_user_id,
        branch_name=payload.branch_name,
        dry_run=bool(payload.dry_run),
    )
    return PredictionApplyResponse(
        prediction_id=result["prediction_id"],
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
    await ensure_loop_project_perm(
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
