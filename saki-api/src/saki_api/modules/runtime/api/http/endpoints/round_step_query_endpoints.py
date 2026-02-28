"""Round/step query endpoints."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import RuntimeServiceDep
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import (
    RoundRead,
    RoundSelectionRead,
    StepRead,
    StepArtifactDownloadResponse,
    StepArtifactsResponse,
    StepCandidateRead,
    StepEventRead,
    StepMetricPointRead,
)
from saki_api.modules.access.domain.rbac import Permissions

router = APIRouter()


@router.get("/rounds/{round_id}", response_model=RoundRead)
async def get_round(
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
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    loop = await runtime_service.loop_repo.get_by_id_or_raise(round_item.loop_id)
    latest_round = await runtime_service.repository.get_latest_by_loop(loop.id)
    loop_mode_text = loop.mode.value
    awaiting_confirm = (
        loop_mode_text == "active_learning"
        and loop.phase.value == "al_wait_user"
        and latest_round is not None
        and latest_round.id == round_item.id
        and round_item.state.value == "completed"
        and round_item.confirmed_at is None
    )
    payload = RoundRead.model_validate(round_item).model_dump()
    payload["awaiting_confirm"] = bool(awaiting_confirm)
    return RoundRead(**payload)


@router.get("/rounds/{round_id}/steps", response_model=List[StepRead])
async def list_round_steps(
    *,
    round_id: uuid.UUID,
    limit: int = Query(default=2000, ge=1, le=5000),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await runtime_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    steps = await runtime_service.list_steps(round_id, limit=limit)
    return [StepRead.model_validate(item) for item in steps]


@router.get("/rounds/{round_id}/selection", response_model=RoundSelectionRead)
async def get_round_selection(
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
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    payload = await runtime_service.get_round_selection(round_id=round_id)
    return RoundSelectionRead.model_validate(payload)


@router.get("/steps/{step_id}", response_model=StepRead)
async def get_step(
    *,
    step_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    return StepRead.model_validate(step)


@router.get("/steps/{step_id}/events", response_model=List[StepEventRead])
async def get_step_events(
    *,
    step_id: uuid.UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=100000),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    events = await runtime_service.list_step_events(step_id, after_seq=after_seq, limit=limit)
    return [StepEventRead(seq=e.seq, ts=e.ts, event_type=e.event_type, payload=e.payload) for e in events]


@router.get("/steps/{step_id}/metrics/series", response_model=List[StepMetricPointRead])
async def get_step_metric_series(
    *,
    step_id: uuid.UUID,
    limit: int = Query(default=5000, ge=1, le=100000),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    points = await runtime_service.list_step_metric_series(step_id, limit=limit)
    return [
        StepMetricPointRead(
            step=item.metric_step,
            epoch=item.epoch,
            metric_name=item.metric_name,
            metric_value=item.metric_value,
            ts=item.ts,
        )
        for item in points
    ]


@router.get("/steps/{step_id}/candidates", response_model=List[StepCandidateRead])
async def get_step_candidates(
    *,
    step_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=5000),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    rows = await runtime_service.list_step_candidates(step_id, limit=limit)
    return [
        StepCandidateRead(
            sample_id=item.sample_id,
            rank=item.rank,
            score=item.score,
            reason=item.reason,
            prediction_snapshot=item.prediction_snapshot,
        )
        for item in rows
    ]


@router.get("/steps/{step_id}/artifacts", response_model=StepArtifactsResponse)
async def get_step_artifacts(
    *,
    step_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    artifacts = await runtime_service.list_step_artifacts(step_id)
    return StepArtifactsResponse(step_id=step_id, artifacts=artifacts)


@router.get("/steps/{step_id}/artifacts/{artifact_name}:download-url", response_model=StepArtifactDownloadResponse)
async def get_step_artifact_download_url(
    *,
    step_id: uuid.UUID,
    artifact_name: str,
    expires_in_hours: int = Query(default=2, ge=1, le=24),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await runtime_service.get_step_by_id_or_raise(step_id)
    round_item = await runtime_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.ROUND_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    download_url = await runtime_service.get_step_artifact_download_url(
        step_id=step_id,
        artifact_name=artifact_name,
        expires_in_hours=expires_in_hours,
    )
    return StepArtifactDownloadResponse(
        step_id=step_id,
        artifact_name=artifact_name,
        download_url=download_url,
        expires_in_hours=expires_in_hours,
    )
