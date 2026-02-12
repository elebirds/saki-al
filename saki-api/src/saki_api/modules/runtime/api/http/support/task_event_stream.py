"""Task-event WebSocket auth and streaming helpers."""

from __future__ import annotations

import asyncio
import uuid

from jose import JWTError, jwt
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocket, WebSocketState

from saki_api.core.config import settings
from saki_api.infra.db.session import SessionLocal
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.service.job import JobService
from saki_api.modules.shared.modeling import Permissions, ResourceType


async def authenticate_stream_token(websocket: WebSocket) -> uuid.UUID | None:
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


async def authorize_stream_task_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_task_id: uuid.UUID,
) -> bool:
    async with SessionLocal() as session:
        task = await session.get(JobTask, parsed_task_id)
        if not task:
            await websocket.close(code=1008, reason="task not found")
            return False
        job_service = JobService(session=session)
        job = await job_service.get_by_id_or_raise(task.job_id)
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


async def stream_task_events_loop(
    *,
    websocket: WebSocket,
    parsed_task_id: uuid.UUID,
    cursor: int,
) -> int:
    while True:
        if websocket.client_state != WebSocketState.CONNECTED:
            break

        async with SessionLocal() as session:  # type: AsyncSession
            job_service = JobService(session=session)
            events = await job_service.list_task_events(parsed_task_id, after_seq=cursor, limit=500)

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
