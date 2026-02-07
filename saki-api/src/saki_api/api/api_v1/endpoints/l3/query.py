import uuid

from fastapi import APIRouter, HTTPException

from saki_api.grpc.runtime_agent import build_query_samples_command, runtime_sessions
from saki_api.schemas.runtime_query import RuntimeQueryRequest, RuntimeQueryResponse

router = APIRouter()


@router.post("/query", response_model=RuntimeQueryResponse)
async def query_samples(request: RuntimeQueryRequest):
    session_obj = runtime_sessions.get_any_agent()
    if not session_obj:
        raise HTTPException(status_code=503, detail="No runtime agent connected")

    request_id = str(uuid.uuid4())
    cmd = build_query_samples_command(
        request_id,
        {
            "project_id": str(request.project_id),
            "source_commit_id": str(request.source_commit_id),
            "plugin_id": request.plugin_id,
            "model_ref": {
                "job_id": str(request.model_ref.job_id),
                "artifact_name": request.model_ref.artifact_name,
            },
            "unit": request.unit,
            "strategy": request.strategy,
            "topk": request.topk,
            "params": request.params,
        },
    )
    await runtime_sessions.send_command(session_obj.agent_id, cmd)
    return RuntimeQueryResponse(request_id=request_id, status="queued")
