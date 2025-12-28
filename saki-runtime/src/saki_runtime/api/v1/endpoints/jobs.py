import asyncio
import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from saki_runtime.api.v1.deps import verify_token, job_manager
from saki_runtime.core.config import settings
from saki_runtime.schemas.jobs import (
    JobCreateRequest,
    JobCreateResponse,
    JobGetResponse,
)

router = APIRouter()

@router.post("", response_model=JobCreateResponse, dependencies=[Depends(verify_token)])
async def create_job(request: JobCreateRequest):
    return await job_manager.create_job(request)

@router.post("/{job_id}:start", dependencies=[Depends(verify_token)])
async def start_job(job_id: str):
    await job_manager.start_job(job_id)
    return {"request_id": str(uuid.uuid4()), "status": "started"}

@router.post("/{job_id}:stop", dependencies=[Depends(verify_token)])
async def stop_job(job_id: str):
    await job_manager.stop_job(job_id)
    return {"request_id": str(uuid.uuid4()), "status": "stopped"}

@router.get("/{job_id}", response_model=JobGetResponse, dependencies=[Depends(verify_token)])
async def get_job(job_id: str):
    info = job_manager.get_job(job_id)
    return JobGetResponse(request_id=str(uuid.uuid4()), job=info)

@router.get("/{job_id}/metrics", dependencies=[Depends(verify_token)])
async def get_job_metrics(job_id: str):
    metrics = job_manager.get_job_metrics(job_id)
    return {"request_id": str(uuid.uuid4()), "metrics": metrics}

@router.get("/{job_id}/artifacts", dependencies=[Depends(verify_token)])
async def get_job_artifacts(job_id: str):
    artifacts = job_manager.list_artifacts(job_id)
    return {"request_id": str(uuid.uuid4()), "artifacts": artifacts}

@router.websocket("/{job_id}/stream")
async def stream_job_events(websocket: WebSocket, job_id: str):
    # WebSocket auth
    token = websocket.query_params.get("token")
    internal_token = websocket.headers.get("x-internal-token")
    
    if internal_token != settings.INTERNAL_TOKEN:
        if token != settings.INTERNAL_TOKEN:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()
    
    try:
        data = await websocket.receive_json()
        if data.get("type") != "subscribe":
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return
            
        since_seq = data.get("since_seq", 0)
        
        ws = job_manager._get_workspace(job_id)
        if not ws.config_path.exists():
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="Job not found")
            return
            
        store = ws.get_event_store()
        
        while True:
            events_found = False
            for event in store.tail(since_seq + 1):
                await websocket.send_text(event.model_dump_json())
                since_seq = event.seq
                events_found = True
            
            if not events_found:
                await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except:
            pass
