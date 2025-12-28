from typing import Any, Dict, Optional
from pydantic import BaseModel

from saki_runtime.schemas.enums import ErrorCode

class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail
