import uuid
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from saki_runtime.core.exceptions import RuntimeErrorBase
from saki_runtime.schemas.errors import ErrorResponse, ErrorDetail
from saki_runtime.schemas.enums import ErrorCode

async def runtime_exception_handler(request: Request, exc: Exception):
    if not isinstance(exc, RuntimeErrorBase):
        # Should not happen if registered correctly
        return await general_exception_handler(request, exc)
        
    request_id = str(uuid.uuid4())
    error_response = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(
            code=exc.error_code,
            message=exc.message,
            details=exc.details
        )
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=error_response.model_dump()
    )

async def validation_exception_handler(request: Request, exc: Exception):
    if not isinstance(exc, RequestValidationError):
        return await general_exception_handler(request, exc)

    request_id = str(uuid.uuid4())
    # exc.errors() contains loc (path), msg, type
    error_response = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Request validation failed",
            details={"validation_errors": exc.errors()}
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump()
    )

async def general_exception_handler(request: Request, exc: Exception):
    request_id = str(uuid.uuid4())
    # In a real app, we should log the full traceback here
    error_response = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(
            code=ErrorCode.INTERNAL,
            message="Internal server error",
            details={"original_error": str(exc)}
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump()
    )
