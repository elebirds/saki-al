import uuid
from fastapi import APIRouter, Depends
from saki_runtime.api.v1.deps import verify_token
from saki_runtime.core.exceptions import invalid_argument
from saki_runtime.schemas.query import QueryRequest, QueryResponse, QueryCandidate

router = APIRouter()

@router.post("", response_model=QueryResponse, dependencies=[Depends(verify_token)])
async def query_samples(request: QueryRequest):
    if request.unit != "image" or request.strategy != "uncertainty":
        raise invalid_argument("Only unit=image and strategy=uncertainty are supported in MVP")

    candidates = []
    for i in range(request.topk):
        candidates.append(QueryCandidate(
            sample_id=f"mock_sample_{i}",
            score=0.9 - (i * 0.01),
            reason={"uncertainty": 0.9 - (i * 0.01)}
        ))
        
    return QueryResponse(
        request_id=str(uuid.uuid4()),
        candidates=candidates
    )
