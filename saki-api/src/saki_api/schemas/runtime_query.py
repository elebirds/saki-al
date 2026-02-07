from typing import Any, Dict, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModelRef(BaseModel):
    job_id: UUID
    artifact_name: str = "best.pt"


class RuntimeQueryRequest(BaseModel):
    project_id: UUID
    source_commit_id: UUID
    plugin_id: str
    model_ref: ModelRef
    unit: Literal["image"] = "image"
    strategy: Literal["uncertainty", "iou_diff", "random"] = "uncertainty"
    topk: int = Field(..., ge=1)
    params: Dict[str, Any]


class RuntimeQueryResponse(BaseModel):
    request_id: str
    status: str
