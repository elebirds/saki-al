from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, Query
from starlette.responses import StreamingResponse

from saki_api.app.deps import TaskServiceDep
from saki_api.core.config import settings
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.importing.schema import ImportTaskStatusResponse

router = APIRouter()


@router.get("/tasks/{task_id}", response_model=ImportTaskStatusResponse)
async def get_import_task_status(
    *,
    task_id: uuid.UUID,
    service: TaskServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskStatusResponse:
    payload = await service.get_status_payload(task_id=task_id, user_id=current_user_id)
    return ImportTaskStatusResponse.model_validate(payload)


@router.get("/tasks/{task_id}/events", response_class=StreamingResponse)
async def stream_import_task_events(
    *,
    task_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    service: TaskServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    heartbeat_seconds = max(1, int(settings.IMPORT_EVENT_HEARTBEAT_SECONDS))

    async def event_stream():
        cursor = max(0, int(after_seq))
        loops_without_data = 0

        while True:
            task, events = await service.list_events_for_user(
                task_id=task_id,
                user_id=current_user_id,
                after_seq=cursor,
                limit=500,
            )
            if events:
                loops_without_data = 0
                for event in events:
                    cursor = max(cursor, int(event.get("seq") or 0))
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if any(str(item.get("event") or "") == "complete" for item in events):
                    return
            else:
                loops_without_data += 1
                if loops_without_data >= heartbeat_seconds:
                    loops_without_data = 0
                    # SSE comment heartbeat; parser should ignore it.
                    yield ": ping\n\n"

                if str(task.status.value if hasattr(task.status, "value") else task.status) in {
                    "success",
                    "failed",
                    "canceled",
                }:
                    return

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
