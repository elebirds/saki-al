"""
全局异常处理。
"""

import json
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from saki_api.core.response import ApiResponse, error_response


async def http_exception_handler(request: Request, exc: FastAPIHTTPException) -> JSONResponse:
    """
    处理HTTPException，转换为统一的响应格式。
    """
    # 从HTTPException中提取detail，可能是字符串或字典
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("detail", detail.get("message", "An error occurred"))
    else:
        message = str(detail)
    
    response = error_response(
        message=message,
        code=exc.status_code
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=json.loads(response.model_dump_json())
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    处理未捕获的异常，转换为统一的响应格式。
    """
    # 记录异常日志
    import logging
    logger = logging.getLogger(__name__)
    logger.exception(f"Unhandled exception: {exc}")
    
    response = error_response(
        message="Internal server error",
        code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=json.loads(response.model_dump_json())
    )

