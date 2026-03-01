"""Step-event WebSocket auth and streaming helpers."""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from fastapi.encoders import jsonable_encoder

from jose import JWTError, jwt
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocket, WebSocketState

from saki_api.core.config import settings
from saki_api.infra.db.session import SessionLocal
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.service.runtime_service import RuntimeService
from saki_api.modules.access.domain.rbac import Permissions, ResourceType


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


async def authorize_stream_step_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_step_id: uuid.UUID,
) -> bool:
    async with SessionLocal() as session:
        step = await session.get(Step, parsed_step_id)
        if not step:
            await websocket.close(code=1008, reason="step not found")
            return False
        runtime_service = RuntimeService(session=session)
        round_row = await runtime_service.get_by_id_or_raise(step.round_id)
        checker = PermissionChecker(session)
        allowed = await checker.check(
            user_id=user_id,
            permission=Permissions.ROUND_READ,
            resource_type=ResourceType.PROJECT,
            resource_id=str(round_row.project_id),
        )
        if not allowed:
            allowed = await checker.check(
                user_id=user_id,
                permission=Permissions.PROJECT_READ,
                resource_type=ResourceType.PROJECT,
                resource_id=str(round_row.project_id),
            )
        if not allowed:
            await websocket.close(code=1008, reason="permission denied")
            return False
    return True


async def stream_step_events_loop(
    *,
    websocket: WebSocket,
    parsed_step_id: uuid.UUID,
    cursor: int,
) -> int:
    disconnect_task: asyncio.Task[dict] | None = None
    sleep_task: asyncio.Task[None] | None = None
    try:
        disconnect_task = asyncio.create_task(websocket.receive())
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break

            async with SessionLocal() as session:  # type: AsyncSession
                runtime_service = RuntimeService(session=session)
                payload = await runtime_service.query_step_events(
                    step_id=parsed_step_id,
                    after_seq=cursor,
                    limit=500,
                )

            events = payload.get("items") or []
            if events:
                for event in events:
                    await websocket.send_json(jsonable_encoder(event))
                    cursor = max(cursor, int(event.get("seq") or 0))

            if disconnect_task is None:
                disconnect_task = asyncio.create_task(websocket.receive())

            sleep_task = asyncio.create_task(asyncio.sleep(1))
            done, pending = await asyncio.wait(
                {disconnect_task, sleep_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                try:
                    message = disconnect_task.result()
                except asyncio.CancelledError:
                    break
                except Exception:
                    break
                if message.get("type") == "websocket.disconnect":
                    break
                disconnect_task = asyncio.create_task(websocket.receive())

            if sleep_task in pending:
                sleep_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sleep_task
            sleep_task = None
    finally:
        if sleep_task is not None and not sleep_task.done():
            sleep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sleep_task
        if disconnect_task is not None and not disconnect_task.done():
            disconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await disconnect_task
    return cursor
