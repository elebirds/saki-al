"""
L3 Job Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.service_deps import JobServiceDep, AnnotationBatchServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models import Permissions, ResourceType
from saki_api.models.enums import TrainingJobStatus
from saki_api.schemas.l3.job import (
    JobCreateRequest,
    JobRead,
    JobCommandResponse,
    JobEventRead,
    JobMetricPointRead,
    JobCandidateRead,
    JobArtifactsResponse,
    JobArtifactRead,
    JobArtifactDownloadResponse,
    AnnotationBatchRead,
    AnnotationBatchCreateRequest,
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
        # Backward-compatible fallback for historical roles not yet granted L3 permissions.
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
        auto_dispatch: bool = Query(True),
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Create a pending runtime job and dispatch to an idle executor.
    """
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.JOB_MANAGE,
    )

    job = await job_service.create_job_for_loop(loop_id, payload)

    if auto_dispatch:
        assigned = await runtime_dispatcher.assign_job(job)
        if not assigned:
            await runtime_dispatcher.dispatch_pending_jobs()
    job = await job_service.get_by_id_or_raise(job.id)

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
    """
    Request executor to stop a job. Operation is idempotent.
    """
    job = await job_service.get_by_id_or_raise(job_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required=Permissions.JOB_MANAGE,
    )
    if job.status in {
        TrainingJobStatus.SUCCESS,
        TrainingJobStatus.FAILED,
        TrainingJobStatus.CANCELLED,
    }:
        return JobCommandResponse(
            request_id=str(uuid.uuid4()),
            job_id=job_id,
            status=job.status.value,
        )

    if not job.assigned_executor_id:
        await job_service.mark_cancelled(job_id, reason=reason)
        return JobCommandResponse(request_id=str(uuid.uuid4()), job_id=job_id, status="cancelled")

    request_id, dispatched = await runtime_dispatcher.stop_job(str(job_id), reason)
    if not dispatched:
        await job_service.mark_cancelled(job_id, reason=reason)
        return JobCommandResponse(request_id=request_id, job_id=job_id, status="cancelled")
    return JobCommandResponse(request_id=request_id, job_id=job_id, status="stopping")


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


@router.get("/jobs/{job_id}/events", response_model=List[JobEventRead])
async def get_job_events(
        *,
        job_id: uuid.UUID,
        after_seq: int = Query(default=0, ge=0),
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
    events = await job_service.list_events(job_id, after_seq=after_seq)
    return [
        JobEventRead(seq=e.seq, ts=e.ts, event_type=e.event_type, payload=e.payload)
        for e in events
    ]


@router.get("/jobs/{job_id}/metrics/series", response_model=List[JobMetricPointRead])
async def get_job_metric_series(
        *,
        job_id: uuid.UUID,
        limit: int = Query(default=5000, ge=1, le=100000),
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
    points = await job_service.list_metric_series(job_id, limit=limit)
    return [
        JobMetricPointRead(
            step=p.step,
            epoch=p.epoch,
            metric_name=p.metric_name,
            metric_value=p.metric_value,
            ts=p.ts,
        )
        for p in points
    ]


@router.get("/jobs/{job_id}/sampling/topk", response_model=List[JobCandidateRead])
async def get_job_sampling_topk(
        *,
        job_id: uuid.UUID,
        limit: int = Query(default=200, ge=1, le=5000),
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
    candidates = await job_service.list_sampling_candidates(job_id, limit=limit)
    return [
        JobCandidateRead(
            sample_id=item.sample_id,
            score=item.score,
            extra=item.extra,
            prediction_snapshot=item.prediction_snapshot,
        )
        for item in candidates
    ]


@router.get("/jobs/{job_id}/artifacts", response_model=JobArtifactsResponse)
async def get_job_artifacts(
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
    artifacts = await job_service.list_artifacts(job_id)
    return JobArtifactsResponse(
        job_id=job_id,
        artifacts=[JobArtifactRead(**item) for item in artifacts],
    )


@router.get("/jobs/{job_id}/artifacts/{artifact_name}:download-url", response_model=JobArtifactDownloadResponse)
async def get_job_artifact_download_url(
        *,
        job_id: uuid.UUID,
        artifact_name: str,
        expires_in_hours: int = Query(default=2, ge=1, le=24),
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
    download_url = await job_service.get_artifact_download_url(
        job_id=job_id,
        artifact_name=artifact_name,
        expires_in_hours=expires_in_hours,
    )
    return JobArtifactDownloadResponse(
        job_id=job_id,
        artifact_name=artifact_name,
        download_url=download_url,
        expires_in_hours=expires_in_hours,
    )


@router.post("/jobs/{job_id}/sampling/batches", response_model=AnnotationBatchRead)
async def create_annotation_batch_from_job(
        *,
        job_id: uuid.UUID,
        payload: AnnotationBatchCreateRequest,
        batch_service: AnnotationBatchServiceDep,
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
    batch = await batch_service.create_from_job(job_id=job_id, limit=payload.limit)
    return AnnotationBatchRead.model_validate(batch)
