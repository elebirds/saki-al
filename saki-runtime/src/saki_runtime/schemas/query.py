from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class ModelRef(BaseModel):
    job_id: str
    artifact_name: str = "best.pt"

class UnlabeledRef(BaseModel):
    dataset_version_id: str
    label_version_id: str

class QueryRequest(BaseModel):
    project_id: str
    plugin_id: str
    model_ref: ModelRef
    unlabeled_ref: UnlabeledRef
    unit: Literal["image"] = "image"
    strategy: Literal["uncertainty"] = "uncertainty"
    topk: int = Field(..., ge=1)
    params: Dict[str, Any]

class QueryCandidate(BaseModel):
    sample_id: str
    score: float
    reason: Optional[Dict[str, Any]] = None

class QueryResponse(BaseModel):
    request_id: str
    candidates: List[QueryCandidate]
