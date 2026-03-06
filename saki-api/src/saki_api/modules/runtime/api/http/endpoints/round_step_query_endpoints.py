"""Round/step query endpoints."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import AssetServiceDep, RuntimeServiceDep
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import (
    RoundArtifactsResponse,
    RoundEventQueryResponse,
    RoundMissingSamplesResponse,
    RoundRead,
    RoundSelectionRead,
    StepRead,
    StepArtifactDownloadResponse,
    StepArtifactsResponse,
    StepCandidateRead,
    TaskEventQueryResponse,
    StepMetricPointRead,
)
from saki_api.modules.access.domain.rbac import Permissions

router = APIRouter()


def _csv_to_list(raw: str | None) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if str(item).strip()]


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
    steps = await runtime_service.list_steps(round_id, limit=5000)
    metric_view = runtime_service.derive_round_metric_view(
        round_item=round_item,
        steps=steps,
    )
    payload = RoundRead.model_validate(round_item).model_dump()
    payload["awaiting_confirm"] = bool(awaiting_confirm)
    payload["final_metrics"] = metric_view.final_metrics
    payload["train_final_metrics"] = metric_view.train_final_metrics
    payload["eval_final_metrics"] = metric_view.eval_final_metrics
    payload["final_metrics_source"] = metric_view.final_metrics_source
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
    )
    payload = await runtime_service.get_round_selection(round_id=round_id)
    return RoundSelectionRead.model_validate(payload)


@router.get("/rounds/{round_id}/artifacts", response_model=RoundArtifactsResponse)
async def get_round_artifacts(
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
    )
    items = await runtime_service.list_round_artifacts(round_id=round_id, limit=limit)
    return RoundArtifactsResponse(round_id=round_id, items=items)


@router.get("/rounds/{round_id}/events", response_model=RoundEventQueryResponse)
async def get_round_events(
    *,
    round_id: uuid.UUID,
    after_cursor: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=100000),
    stages: str | None = Query(default=None),
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
    )
    payload = await runtime_service.query_round_events(
        round_id=round_id,
        after_cursor=after_cursor,
        limit=limit,
        stages=_csv_to_list(stages),
    )
    return RoundEventQueryResponse.model_validate(payload)


@router.get("/loops/{loop_id}/rounds/{round_id}/missing-samples", response_model=RoundMissingSamplesResponse)
async def get_round_missing_samples(
    *,
    loop_id: uuid.UUID,
    round_id: uuid.UUID,
    dataset_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    sort_by: str = Query(default="createdAt"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=200),
    runtime_service: RuntimeServiceDep,
    asset_service: AssetServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required_permission=Permissions.LOOP_READ,
    )
    payload = await runtime_service.list_round_missing_samples(
        loop_id=loop_id,
        round_id=round_id,
        current_user_id=current_user_id,
        dataset_id=dataset_id,
        q=q,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit,
    )
    for item in payload.get("items") or []:
        primary_asset_id = item.get("primary_asset_id")
        if not primary_asset_id:
            continue
        try:
            item["primary_asset_url"] = await asset_service.get_presigned_download_url(primary_asset_id)
        except Exception:
            continue
    return RoundMissingSamplesResponse.model_validate(payload)


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
    )
    return StepRead.model_validate(step)


@router.get("/tasks/{task_id}/events", response_model=TaskEventQueryResponse)
async def get_task_events(
    *,
    task_id: uuid.UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=100000),
    event_types: str | None = Query(default=None),
    levels: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    q: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    include_facets: bool = Query(default=False),
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await runtime_service.task_repo.get_by_id_or_raise(task_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=task.project_id,
        required_permission=Permissions.ROUND_READ,
    )
    payload = await runtime_service.query_task_events(
        task_id=task_id,
        after_seq=after_seq,
        limit=limit,
        event_types=_csv_to_list(event_types),
        levels=_csv_to_list(levels),
        tags=_csv_to_list(tags),
        q=q,
        from_ts=from_ts,
        to_ts=to_ts,
        include_facets=include_facets,
    )
    return TaskEventQueryResponse.model_validate(payload)


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
        if int(item.metric_step or 0) > 0
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
