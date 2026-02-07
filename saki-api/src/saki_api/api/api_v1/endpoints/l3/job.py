"""
L3 Job Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Query

from saki_api.api.service_deps import JobServiceDep
from saki_api.grpc.dispatcher import runtime_dispatcher
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
)

router = APIRouter()


@router.post("/loops/{loop_id}/jobs", response_model=JobRead)
async def create_job(
        *,
        loop_id: uuid.UUID,
        payload: JobCreateRequest,
        auto_dispatch: bool = Query(True),
        job_service: JobServiceDep,
):
    """
    Create a pending runtime job and dispatch to an idle executor.
    """
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
):
    """
    Request executor to stop a job. Operation is idempotent.
    """
    job = await job_service.get_by_id_or_raise(job_id)
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
):
    job = await job_service.get_by_id_or_raise(job_id)
    return JobRead.model_validate(job)


@router.get("/jobs/{job_id}/events", response_model=List[JobEventRead])
async def get_job_events(
        *,
        job_id: uuid.UUID,
        after_seq: int = Query(default=0, ge=0),
        job_service: JobServiceDep,
):
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
):
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
):
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
):
    artifacts = await job_service.list_artifacts(job_id)
    return JobArtifactsResponse(
        job_id=job_id,
        artifacts=[JobArtifactRead(**item) for item in artifacts],
    )
