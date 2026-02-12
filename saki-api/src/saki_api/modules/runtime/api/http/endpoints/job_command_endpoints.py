"""Job/task command endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import JobServiceDep
from saki_api.infra.db.session import get_session
from saki_api.infra.grpc.dispatcher import runtime_dispatcher
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.job import JobCommandResponse, JobCreateRequest, JobRead, TaskCommandResponse
from saki_api.modules.shared.modeling import Permissions
from saki_api.modules.shared.modeling.enums import JobStatusV2, JobTaskStatus

router = APIRouter()


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
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
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
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
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
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=job.project_id,
        required_permission=Permissions.JOB_MANAGE,
        fallback_permissions=(Permissions.PROJECT_UPDATE,),
    )

    if task.status in {JobTaskStatus.SUCCEEDED, JobTaskStatus.FAILED, JobTaskStatus.CANCELLED, JobTaskStatus.SKIPPED}:
        return TaskCommandResponse(request_id=str(uuid.uuid4()), task_id=task_id, status=task.status.value)

    if task.assigned_executor_id:
        request_id, dispatched = await runtime_dispatcher.stop_task(str(task_id), reason)
        if dispatched:
            return TaskCommandResponse(request_id=request_id, task_id=task_id, status="stopping")

    cancelled = await job_service.mark_task_cancelled(task_id, reason=reason)
    return TaskCommandResponse(request_id=str(uuid.uuid4()), task_id=task_id, status=cancelled.status.value)
