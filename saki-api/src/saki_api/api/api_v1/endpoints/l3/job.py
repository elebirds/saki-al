import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.db.session import get_session
from saki_api.grpc.runtime_agent import (
    build_create_job_command,
    build_start_job_command,
    build_stop_job_command,
    runtime_sessions,
)
from saki_api.models.l3.job import Job
from saki_api.models.l3.loop import ALLoop
from saki_api.models.enums import TrainingJobStatus
from saki_api.schemas.job import JobCreateRequest, JobRead, JobCommandResponse

router = APIRouter()


@router.post("/loops/{loop_id}/jobs", response_model=JobRead)
async def create_job(
    loop_id: uuid.UUID,
    job_in: JobCreateRequest,
    auto_start: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    loop = await session.get(ALLoop, loop_id)
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")
    if str(loop.project_id) != str(job_in.project_id):
        raise HTTPException(status_code=400, detail="Project mismatch with loop")

    session_obj = runtime_sessions.get_any_agent()
    if not session_obj:
        raise HTTPException(status_code=503, detail="No runtime agent connected")

    iteration = loop.current_iteration + 1
    loop.current_iteration = iteration
    session.add(loop)

    job = Job(
        project_id=job_in.project_id,
        loop_id=loop_id,
        iteration=iteration,
        status=TrainingJobStatus.PENDING,
        source_commit_id=job_in.source_commit_id,
        job_type=job_in.job_type,
        plugin_id=job_in.plugin_id,
        params=job_in.params,
        resources=job_in.resources,
        metrics={},
        artifacts={},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    request_id = str(uuid.uuid4())
    create_cmd = build_create_job_command(request_id, job)
    await runtime_sessions.send_command(session_obj.agent_id, create_cmd)

    if auto_start:
        start_cmd = build_start_job_command(str(uuid.uuid4()), str(job.id))
        await runtime_sessions.send_command(session_obj.agent_id, start_cmd)

    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}:start", response_model=JobCommandResponse)
async def start_job(job_id: uuid.UUID):
    session_obj = runtime_sessions.get_any_agent()
    if not session_obj:
        raise HTTPException(status_code=503, detail="No runtime agent connected")
    request_id = str(uuid.uuid4())
    cmd = build_start_job_command(request_id, str(job_id))
    await runtime_sessions.send_command(session_obj.agent_id, cmd)
    return JobCommandResponse(request_id=request_id, job_id=job_id, status="queued")


@router.post("/jobs/{job_id}:stop", response_model=JobCommandResponse)
async def stop_job(job_id: uuid.UUID):
    session_obj = runtime_sessions.get_any_agent()
    if not session_obj:
        raise HTTPException(status_code=503, detail="No runtime agent connected")
    request_id = str(uuid.uuid4())
    cmd = build_stop_job_command(request_id, str(job_id))
    await runtime_sessions.send_command(session_obj.agent_id, cmd)
    return JobCommandResponse(request_id=request_id, job_id=job_id, status="stopping")


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead.model_validate(job)
