from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class GPUResource(BaseModel):
    count: int = Field(..., description="Must be 1 for MVP")
    device_ids: List[int] = Field(..., description="Must have exactly 1 element")

    @field_validator("count")
    @classmethod
    def validate_count(cls, v: int) -> int:
        if v != 1:
            raise ValueError("GPU count must be 1 for MVP")
        return v

    @field_validator("device_ids")
    @classmethod
    def validate_device_ids(cls, v: List[int]) -> List[int]:
        if len(v) != 1:
            raise ValueError("device_ids must have exactly 1 element")
        return v

class CPUResource(BaseModel):
    workers: int = Field(..., ge=1)

class JobResources(BaseModel):
    gpu: GPUResource
    cpu: Optional[CPUResource] = None
    memory_mb: Optional[int] = None
