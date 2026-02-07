"""
L3 Query Endpoints for loop/job listing.
"""

import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlmodel import select
from starlette.websockets import WebSocketState

from saki_api.api.service_deps import JobServiceDep
from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.models.l3.job_event import JobEvent
from saki_api.schemas.l3.job import JobRead, LoopCreateRequest, LoopRead

router = APIRouter()


@router.get("/projects/{project_id}/loops", response_model=List[LoopRead])
async def list_project_loops(
        *,
        project_id: uuid.UUID,
        job_service: JobServiceDep,
):
    loops = await job_service.list_loops(project_id)
    return [LoopRead.model_validate(item) for item in loops]


@router.post("/projects/{project_id}/loops", response_model=LoopRead)
async def create_project_loop(
        *,
        project_id: uuid.UUID,
        payload: LoopCreateRequest,
        job_service: JobServiceDep,
):
    loop = await job_service.create_loop(project_id, payload)
    return LoopRead.model_validate(loop)


@router.get("/loops/{loop_id}/jobs", response_model=List[JobRead])
async def list_loop_jobs(
        *,
        loop_id: uuid.UUID,
        limit: int = Query(default=50, ge=1, le=1000),
        job_service: JobServiceDep,
):
    jobs = await job_service.list_jobs(loop_id, limit=limit)
    return [JobRead.model_validate(item) for item in jobs]


@router.websocket("/jobs/{job_id}/events/ws")
async def stream_job_events(
        websocket: WebSocket,
        job_id: str,
        after_seq: int = 0,
):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="missing token")
        return
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("sub"):
            raise JWTError("invalid token payload")
    except JWTError:
        await websocket.close(code=1008, reason="invalid token")
        return

    try:
        parsed_job_id = uuid.UUID(job_id)
    except Exception:
        await websocket.close(code=1008, reason="invalid job_id")
        return

    await websocket.accept()
    cursor = max(0, after_seq)
    try:
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            async with SessionLocal() as session:
                rows = await session.exec(
                    select(JobEvent)
                    .where(JobEvent.job_id == parsed_job_id, JobEvent.seq > cursor)
                    .order_by(JobEvent.seq.asc())
                    .limit(500)
                )
                events = list(rows.all())

            if events:
                for event in events:
                    await websocket.send_json(
                        {
                            "seq": event.seq,
                            "ts": event.ts.isoformat(),
                            "event_type": event.event_type,
                            "payload": event.payload,
                        }
                    )
                    cursor = max(cursor, event.seq)

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception:
        return
