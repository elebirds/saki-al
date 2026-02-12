"""L3 Job/Task endpoints."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.service_deps import JobServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models import Permissions, ResourceType
from saki_api.models.enums import JobStatusV2, JobTaskStatus
from saki_api.schemas.runtime.job import (
    JobCommandResponse,
    JobCreateRequest,
    JobRead,
    JobTaskRead,
    TaskArtifactDownloadResponse,
    TaskArtifactsResponse,
    TaskArtifactRead,
    TaskCandidateRead,
    TaskCommandResponse,
    TaskEventRead,
    TaskMetricPointRead,
)

router = APIRouter()


async def _ensure_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    checker = PermissionChecker(session)
    ok = await checker.check(
        user_id=current_user_id,
        permission=required,
        resource_type=ResourceType.PROJECT,
        resource_id=str(project_id),
    )
    if not ok:
        fallback = Permissions.PROJECT_READ if required == Permissions.JOB_READ else Permissions.PROJECT_UPDATE
        ok = await checker.check(
            user_id=current_user_id,
            permission=fallback,
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
        )
    if not ok:
        raise ForbiddenAppException(f"Permission denied: {required}")


@router.post("/loops/{loop_id}/jobs", response_model=JobRead)
async def create_job(
    *,
    loop_id: uuid.UUID,
    payload: JobCreateRequest,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.JOB_MANAGE,
    )
    job = await job_service.create_job_for_loop(loop_id, payload)
    await runtime_dispatcher.dispatch_pending_tasks()
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}:stop", response_model=JobCommandResponse)
async def stop_job(
    *,
    job_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    job = await job_service.get_by_id_or_raise(job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_MANAGE,
    )

    if job.summary_status in {
        JobStatusV2.JOB_SUCCEEDED,
        JobStatusV2.JOB_FAILED,
        JobStatusV2.JOB_PARTIAL_FAILED,
        JobStatusV2.JOB_CANCELLED,
    }:
        return JobCommandResponse(
            request_id=str(uuid.uuid4()),
            job_id=job_id,
            status=job.summary_status.value,
        )

    tasks = await job_service.list_tasks(job_id, limit=2000)
    dispatched_any = False
    request_id = str(uuid.uuid4())
    for task in tasks:
        if task.status in {JobTaskStatus.RUNNING, JobTaskStatus.DISPATCHING, JobTaskStatus.RETRYING}:
            request_id, dispatched = await runtime_dispatcher.stop_task(str(task.id), reason)
            dispatched_any = dispatched_any or dispatched

    if not dispatched_any:
        await job_service.mark_job_cancelled(job_id, reason=reason)
        status = JobStatusV2.JOB_CANCELLED.value
    else:
        status = "stopping"

    return JobCommandResponse(request_id=request_id, job_id=job_id, status=status)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(
    *,
    job_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    job = await job_service.get_by_id_or_raise(job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    return JobRead.model_validate(job)


@router.get("/jobs/{job_id}/tasks", response_model=List[JobTaskRead])
async def list_job_tasks(
    *,
    job_id: uuid.UUID,
    limit: int = Query(default=2000, ge=1, le=5000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    job = await job_service.get_by_id_or_raise(job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    tasks = await job_service.list_tasks(job_id, limit=limit)
    return [JobTaskRead.model_validate(item) for item in tasks]


@router.get("/tasks/{task_id}", response_model=JobTaskRead)
async def get_task(
    *,
    task_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    return JobTaskRead.model_validate(task)


@router.post("/tasks/{task_id}:stop", response_model=TaskCommandResponse)
async def stop_task(
    *,
    task_id: uuid.UUID,
    reason: str = Query(default="user requested stop"),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_MANAGE,
    )

    if task.status in {JobTaskStatus.SUCCEEDED, JobTaskStatus.FAILED, JobTaskStatus.CANCELLED, JobTaskStatus.SKIPPED}:
        return TaskCommandResponse(request_id=str(uuid.uuid4()), task_id=task_id, status=task.status.value)

    if task.assigned_executor_id:
        request_id, dispatched = await runtime_dispatcher.stop_task(str(task_id), reason)
        if dispatched:
            return TaskCommandResponse(request_id=request_id, task_id=task_id, status="stopping")

    cancelled = await job_service.mark_task_cancelled(task_id, reason=reason)
    return TaskCommandResponse(request_id=str(uuid.uuid4()), task_id=task_id, status=cancelled.status.value)


@router.get("/tasks/{task_id}/events", response_model=List[TaskEventRead])
async def get_task_events(
    *,
    task_id: uuid.UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=100000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    events = await job_service.list_task_events(task_id, after_seq=after_seq, limit=limit)
    return [TaskEventRead(seq=e.seq, ts=e.ts, event_type=e.event_type, payload=e.payload) for e in events]


@router.get("/tasks/{task_id}/metrics/series", response_model=List[TaskMetricPointRead])
async def get_task_metric_series(
    *,
    task_id: uuid.UUID,
    limit: int = Query(default=5000, ge=1, le=100000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    points = await job_service.list_task_metric_series(task_id, limit=limit)
    return [
        TaskMetricPointRead(
            step=item.step,
            epoch=item.epoch,
            metric_name=item.metric_name,
            metric_value=item.metric_value,
            ts=item.ts,
        )
        for item in points
    ]


@router.get("/tasks/{task_id}/candidates", response_model=List[TaskCandidateRead])
async def get_task_candidates(
    *,
    task_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=5000),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    rows = await job_service.list_task_candidates(task_id, limit=limit)
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


@router.get("/tasks/{task_id}/artifacts", response_model=TaskArtifactsResponse)
async def get_task_artifacts(
    *,
    task_id: uuid.UUID,
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    artifacts = await job_service.list_task_artifacts(task_id)
    return TaskArtifactsResponse(task_id=task_id, artifacts=[TaskArtifactRead(**item) for item in artifacts])


@router.get("/tasks/{task_id}/artifacts/{artifact_name}:download-url", response_model=TaskArtifactDownloadResponse)
async def get_task_artifact_download_url(
    *,
    task_id: uuid.UUID,
    artifact_name: str,
    expires_in_hours: int = Query(default=2, ge=1, le=24),
    job_service: JobServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    task = await job_service.get_task_by_id_or_raise(task_id)
    job = await job_service.get_by_id_or_raise(task.job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_READ,
    )
    download_url = await job_service.get_task_artifact_download_url(
        task_id=task_id,
        artifact_name=artifact_name,
        expires_in_hours=expires_in_hours,
    )
    return TaskArtifactDownloadResponse(
        task_id=task_id,
        artifact_name=artifact_name,
        download_url=download_url,
        expires_in_hours=expires_in_hours,
    )
