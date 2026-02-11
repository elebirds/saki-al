"""
L3 Query Endpoints for loop/job listing.
"""

import asyncio
import contextlib
import uuid
from typing import List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Depends
from jose import JWTError, jwt
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocketState

from saki_api.api.service_deps import JobServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.core.config import settings
from saki_api.db.session import SessionLocal, get_session
from saki_api.models import Permissions, ResourceType
from saki_api.models.l3.job import Job
from saki_api.schemas.l3.job import (
    JobRead,
    LoopCreateRequest,
    LoopUpdateRequest,
    LoopRead,
    LoopRoundRead,
    LoopSummaryRead,
    SimulationExperimentCreateRequest,
    SimulationExperimentCreateResponse,
    SimulationExperimentCurvesRead,
)
from saki_api.services.loop_config import extract_model_request_config, extract_simulation_config
from saki_api.services.job import JobService

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
        fallback = Permissions.PROJECT_READ if required in {Permissions.LOOP_READ, Permissions.JOB_READ} else Permissions.PROJECT_UPDATE
        ok = await checker.check(
            user_id=current_user_id,
            permission=fallback,
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
        )
    if not ok:
        raise ForbiddenAppException(f"Permission denied: {required}")


def _build_loop_read(loop) -> LoopRead:
    row = LoopRead.model_validate(loop, from_attributes=True)
    return row.model_copy(
        update={
            "model_request_config": extract_model_request_config(getattr(loop, "global_config", {})),
            "simulation_config": extract_simulation_config(getattr(loop, "global_config", {})),
        }
    )


async def _authenticate_stream_token(websocket: WebSocket) -> uuid.UUID | None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="missing token")
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("sub"):
            raise JWTError("invalid token payload")
        return uuid.UUID(str(payload["sub"]))
    except JWTError:
        await websocket.close(code=1008, reason="invalid token")
        return None
    except Exception:
        await websocket.close(code=1008, reason="invalid token subject")
        return None


async def _authorize_stream_job_access(
        *,
        websocket: WebSocket,
        user_id: uuid.UUID,
        parsed_job_id: uuid.UUID,
) -> bool:
    async with SessionLocal() as session:
        job = await session.get(Job, parsed_job_id)
        if not job:
            await websocket.close(code=1008, reason="job not found")
            return False
        checker = PermissionChecker(session)
        allowed = await checker.check(
            user_id=user_id,
            permission=Permissions.JOB_READ,
            resource_type=ResourceType.PROJECT,
            resource_id=str(job.project_id),
        )
        if not allowed:
            allowed = await checker.check(
                user_id=user_id,
                permission=Permissions.PROJECT_READ,
                resource_type=ResourceType.PROJECT,
                resource_id=str(job.project_id),
            )
        if not allowed:
            await websocket.close(code=1008, reason="permission denied")
            return False
    return True


async def _stream_job_events_loop(
        *,
        websocket: WebSocket,
        parsed_job_id: uuid.UUID,
        cursor: int,
) -> int:
    while True:
        if websocket.client_state != WebSocketState.CONNECTED:
            break

        async with SessionLocal() as session:
            job_service = JobService(session=session)
            events = await job_service.list_events_chunk(
                parsed_job_id,
                after_seq=cursor,
                limit=500,
                ensure_job_exists=False,
            )

        if events:
            for event in events:
                await websocket.send_json(
                    {
                        "seq": event.seq,
                        "ts": event.ts.isoformat(),
                        "eventType": event.event_type,
                        "event_type": event.event_type,
                        "payload": event.payload,
                    }
                )
                cursor = max(cursor, event.seq)

        await asyncio.sleep(1)
    return cursor


@router.get("/projects/{project_id}/loops", response_model=List[LoopRead])
async def list_project_loops(
        *,
        project_id: uuid.UUID,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_READ,
    )
    loops = await job_service.list_loops(project_id)
    return [_build_loop_read(item) for item in loops]


@router.post("/projects/{project_id}/simulation-experiments", response_model=SimulationExperimentCreateResponse)
async def create_simulation_experiment(
        *,
        project_id: uuid.UUID,
        payload: SimulationExperimentCreateRequest,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    group_id, loops = await job_service.create_simulation_experiment(
        project_id=project_id,
        payload=payload,
    )
    return SimulationExperimentCreateResponse(
        experiment_group_id=group_id,
        loops=[_build_loop_read(item) for item in loops],
    )


@router.post("/projects/{project_id}/loops", response_model=LoopRead)
async def create_project_loop(
        *,
        project_id: uuid.UUID,
        payload: LoopCreateRequest,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.LOOP_MANAGE,
    )
    loop = await job_service.create_loop(project_id, payload)
    return _build_loop_read(loop)


@router.get("/loops/{loop_id}", response_model=LoopRead)
async def get_loop(
        *,
        loop_id: uuid.UUID,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    return _build_loop_read(loop)


@router.patch("/loops/{loop_id}", response_model=LoopRead)
async def update_loop(
        *,
        loop_id: uuid.UUID,
        payload: LoopUpdateRequest,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_MANAGE,
    )
    updated = await job_service.update_loop(loop_id, payload)
    return _build_loop_read(updated)


@router.get("/loops/{loop_id}/jobs", response_model=List[JobRead])
async def list_loop_jobs(
        *,
        loop_id: uuid.UUID,
        limit: int = Query(default=50, ge=1, le=1000),
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.JOB_READ,
    )
    jobs = await job_service.list_jobs(loop_id, limit=limit)
    return [JobRead.model_validate(item) for item in jobs]


@router.get("/loops/{loop_id}/rounds", response_model=List[LoopRoundRead])
async def list_loop_rounds(
        *,
        loop_id: uuid.UUID,
        limit: int = Query(default=200, ge=1, le=2000),
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    rounds = await job_service.list_rounds(loop_id, limit=limit, ensure_loop_exists=False)
    return [LoopRoundRead.model_validate(item) for item in rounds]


@router.get("/loops/{loop_id}/summary", response_model=LoopSummaryRead)
async def get_loop_summary(
        *,
        loop_id: uuid.UUID,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    summary = await job_service.summarize_loop(loop_id, ensure_loop_exists=False)
    return LoopSummaryRead(
        loop_id=loop.id,
        status=loop.status,
        rounds_total=int(summary["rounds_total"]),
        rounds_completed=int(summary["rounds_completed"]),
        selected_total=int(summary["selected_total"]),
        labeled_total=int(summary["labeled_total"]),
        metrics_latest=summary["metrics_latest"],
    )


@router.get("/simulation-experiments/{group_id}/curves", response_model=SimulationExperimentCurvesRead)
async def get_simulation_experiment_curves(
        *,
        group_id: uuid.UUID,
        job_service: JobServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    payload = await job_service.get_simulation_experiment_curves(experiment_group_id=group_id)
    # 权限校验：任一 loop 的 project 可访问则返回（同组 loop 必属同项目）
    loop_id = payload["loops"][0]["loop_id"]
    loop = await job_service.loop_repo.get_by_id_or_raise(loop_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    return SimulationExperimentCurvesRead.model_validate(payload)


@router.websocket("/jobs/{job_id}/events/ws")
async def stream_job_events(
        websocket: WebSocket,
        job_id: str,
        after_seq: int = 0,
):
    user_id = await _authenticate_stream_token(websocket)
    if user_id is None:
        return

    try:
        parsed_job_id = uuid.UUID(job_id)
    except Exception:
        await websocket.close(code=1008, reason="invalid job_id")
        return

    authorized = await _authorize_stream_job_access(
        websocket=websocket,
        user_id=user_id,
        parsed_job_id=parsed_job_id,
    )
    if not authorized:
        return

    await websocket.accept()
    cursor = max(0, after_seq)
    try:
        cursor = await _stream_job_events_loop(
            websocket=websocket,
            parsed_job_id=parsed_job_id,
            cursor=cursor,
        )
    except WebSocketDisconnect:
        logger.debug("任务事件流连接断开 job_id={} after_seq={}", parsed_job_id, cursor)
        return
    except Exception:
        logger.exception("任务事件流处理失败 job_id={} after_seq={}", parsed_job_id, cursor)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1011, reason="internal error")
        return
