"""Round/step query endpoints."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import JobServiceDep
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.job import (
    JobRead,
    JobTaskRead,
    TaskArtifactDownloadResponse,
    TaskArtifactsResponse,
    TaskCandidateRead,
    TaskEventRead,
    TaskMetricPointRead,
)
from saki_api.modules.shared.modeling import Permissions

router = APIRouter()


@router.get("/rounds/{round_id}", response_model=JobRead)
async def get_round(
    *,
    round_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await job_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    return JobRead.model_validate(round_item)


@router.get("/rounds/{round_id}/steps", response_model=List[JobTaskRead])
async def list_round_steps(
    *,
    round_id: uuid.UUID,
    limit: int = Query(default=2000, ge=1, le=5000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    round_item = await job_service.get_by_id_or_raise(round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    steps = await job_service.list_tasks(round_id, limit=limit)
    return [JobTaskRead.model_validate(item) for item in steps]


@router.get("/steps/{step_id}", response_model=JobTaskRead)
async def get_step(
    *,
    step_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    return JobTaskRead.model_validate(step)


@router.get("/steps/{step_id}/events", response_model=List[TaskEventRead])
async def get_step_events(
    *,
    step_id: uuid.UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=100000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    events = await job_service.list_task_events(step_id, after_seq=after_seq, limit=limit)
    return [TaskEventRead(seq=e.seq, ts=e.ts, event_type=e.event_type, payload=e.payload) for e in events]


@router.get("/steps/{step_id}/metrics/series", response_model=List[TaskMetricPointRead])
async def get_step_metric_series(
    *,
    step_id: uuid.UUID,
    limit: int = Query(default=5000, ge=1, le=100000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    points = await job_service.list_task_metric_series(step_id, limit=limit)
    return [
        TaskMetricPointRead(
            step=item.metric_step,
            epoch=item.epoch,
            metric_name=item.metric_name,
            metric_value=item.metric_value,
            ts=item.ts,
        )
        for item in points
    ]


@router.get("/steps/{step_id}/candidates", response_model=List[TaskCandidateRead])
async def get_step_candidates(
    *,
    step_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=5000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    rows = await job_service.list_task_candidates(step_id, limit=limit)
    return [
        TaskCandidateRead(
            sample_id=item.sample_id,
            rank=item.rank,
            score=item.score,
            reason=item.reason,
            prediction_snapshot=item.prediction_snapshot,
        )
        for item in rows
    ]


@router.get("/steps/{step_id}/artifacts", response_model=TaskArtifactsResponse)
async def get_step_artifacts(
    *,
    step_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    artifacts = await job_service.list_task_artifacts(step_id)
    return TaskArtifactsResponse(step_id=step_id, artifacts=artifacts)


@router.get("/steps/{step_id}/artifacts/{artifact_name}:download-url", response_model=TaskArtifactDownloadResponse)
async def get_step_artifact_download_url(
    *,
    step_id: uuid.UUID,
    artifact_name: str,
    expires_in_hours: int = Query(default=2, ge=1, le=24),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    step = await job_service.get_task_by_id_or_raise(step_id)
    round_item = await job_service.get_by_id_or_raise(step.round_id)
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=round_item.project_id,
        required_permission=Permissions.JOB_READ,
        fallback_permissions=(Permissions.PROJECT_READ,),
    )
    download_url = await job_service.get_task_artifact_download_url(
        task_id=step_id,
        artifact_name=artifact_name,
        expires_in_hours=expires_in_hours,
    )
    return TaskArtifactDownloadResponse(
        step_id=step_id,
        artifact_name=artifact_name,
        download_url=download_url,
        expires_in_hours=expires_in_hours,
    )
