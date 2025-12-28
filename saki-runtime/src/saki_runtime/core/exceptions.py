from typing import Any, Dict, Optional
from saki_runtime.schemas.enums import ErrorCode

class RuntimeErrorBase(Exception):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        http_status: int,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details
        super().__init__(message)

def invalid_argument(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.INVALID_ARGUMENT, message, 400, details)

def not_found(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.NOT_FOUND, message, 404, details)

def conflict(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.CONFLICT, message, 409, details)

def unauthorized(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.UNAUTHORIZED, message, 401, details)

def forbidden(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.FORBIDDEN, message, 403, details)

def unavailable(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.UNAVAILABLE, message, 503, details)

def internal_error(message: str, details: Optional[Dict[str, Any]] = None) -> RuntimeErrorBase:
    return RuntimeErrorBase(ErrorCode.INTERNAL, message, 500, details)
