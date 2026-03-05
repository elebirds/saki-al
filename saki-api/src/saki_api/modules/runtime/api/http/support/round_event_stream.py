"""Round-event WebSocket auth and streaming helpers."""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from fastapi.encoders import jsonable_encoder
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocket, WebSocketState

from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.session import SessionLocal
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.service.runtime_service import RuntimeService


async def authorize_stream_round_access(
    *,
    websocket: WebSocket,
    user_id: uuid.UUID,
    parsed_round_id: uuid.UUID,
) -> bool:
    async with SessionLocal() as session:
        runtime_service = RuntimeService(session=session)
        try:
            round_row = await runtime_service.get_by_id_or_raise(parsed_round_id)
        except Exception:
            await websocket.close(code=1008, reason="round not found")
            return False

        checker = PermissionChecker(session)
        allowed = await checker.check(
            user_id=user_id,
            permission=Permissions.ROUND_READ,
            resource_type=ResourceType.PROJECT,
            resource_id=str(round_row.project_id),
        )
        if not allowed:
            await websocket.close(code=1008, reason="permission denied")
            return False
    return True


async def stream_round_events_loop(
    *,
    websocket: WebSocket,
    parsed_round_id: uuid.UUID,
    after_cursor: str | None,
    stages: list[str] | None,
    limit: int = 5000,
) -> str | None:
    cursor = str(after_cursor or "").strip() or None
    disconnect_task: asyncio.Task[dict] | None = None
    sleep_task: asyncio.Task[None] | None = None
    try:
        disconnect_task = asyncio.create_task(websocket.receive())
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break

            async with SessionLocal() as session:  # type: AsyncSession
                runtime_service = RuntimeService(session=session)
                payload = await runtime_service.query_round_events(
                    round_id=parsed_round_id,
                    after_cursor=cursor,
                    limit=limit,
                    stages=stages,
                )

            items = payload.get("items") or []
            if items:
                for event in items:
                    await websocket.send_json(jsonable_encoder(event))
                cursor = payload.get("next_after_cursor") or cursor
                if bool(payload.get("has_more")):
                    continue

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
    except BadRequestAppException:
        raise
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
