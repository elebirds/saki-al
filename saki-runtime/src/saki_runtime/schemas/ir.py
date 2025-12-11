from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

class SampleIR(BaseModel):
    id: str
    uri: str
    width: int
    height: int
    meta: Optional[Dict[str, Any]] = None

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        if not (v.startswith("file://") or v.startswith("s3://")):
            raise ValueError("URI must start with 'file://' or 's3://'")
        return v

class LabelIR(BaseModel):
    id: int
    name: str
    color: Optional[str] = None

class DetAnnotationIR(BaseModel):
    id: Optional[str] = None
    sample_id: str
    category_id: int
    bbox_xywh: List[float]
    obb: Optional[Dict[str, Any]] = None
    source: str
    confidence: Optional[float] = None

    @field_validator("bbox_xywh")
    @classmethod
    def validate_bbox(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError("bbox_xywh must have exactly 4 elements")
        return v
