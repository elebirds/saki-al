"""
全局异常处理。
"""

import logging
from typing import Optional

from fastapi import Request, status
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse

from saki_api.core.enums import ErrorCode
from saki_api.core.response import ApiResponse

logger = logging.getLogger(__name__)


class AppException(Exception):
    """
    业务异常基类。
    
    用于替代 HTTPException，提供更语义化的错误处理。
    自动根据 ErrorCode 映射到对应的 HTTP 状态码。
    """

    def __init__(
            self,
            message: str,
            error_code: ErrorCode = ErrorCode.BAD_REQUEST,
            status_code: Optional[int] = None,
            data: Optional[dict] = None
    ):
        """
        初始化业务异常。
        
        Args:
            message: 错误消息
            error_code: 业务错误码
            status_code: HTTP状态码（如果为None，则根据error_code自动映射）
            data: 可选的错误详情数据
        """
        self.message = message
        self.error_code = error_code
        self.data = data
        self.status_code = status_code or self._map_error_code_to_status_code(error_code)
        super().__init__(self.message)

    @staticmethod
    def _map_error_code_to_status_code(error_code: ErrorCode) -> int:
        # 1. 认证相关：只有没登录才 401，剩下的（如密码错）其实可以算 400
        if error_code in (ErrorCode.UNAUTHORIZED, ErrorCode.AUTH_INVALID_TOKEN):
            return status.HTTP_401_UNAUTHORIZED

        # 2. 权限相关：403
        if error_code in (ErrorCode.FORBIDDEN, ErrorCode.AUTH_PERMISSION_DENIED):
            return status.HTTP_403_FORBIDDEN

        # 3. 严重的系统崩溃：500
        if error_code == ErrorCode.INTERNAL_SERVER_ERROR:
            return status.HTTP_500_INTERNAL_SERVER_ERROR

        # 4. 其他所有业务报错，一律返回 400
        # 既能让浏览器控制台变红方便调试，又不用纠结是 404 还是 409
        return status.HTTP_400_BAD_REQUEST


class NotFoundAppException(AppException):
    def __init__(self, message: str = "Not Found"):
        super().__init__(message, ErrorCode.NOT_FOUND)


class BadRequestAppException(AppException):
    def __init__(self, message: str = "Bad Request"):
        super().__init__(message, ErrorCode.BAD_REQUEST)


class UnauthorizedAppException(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, ErrorCode.UNAUTHORIZED)


class ForbiddenAppException(AppException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, ErrorCode.FORBIDDEN)


class InternalServerErrorAppException(AppException):
    def __init__(self, message: str = "Internal Server Error"):
        super().__init__(message, ErrorCode.INTERNAL_SERVER_ERROR)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    处理业务异常（AppException），转换为统一的响应格式。
    """
    response = ApiResponse.error_response(
        message=exc.message,
        code=exc.error_code.value,
        data=exc.data
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump()
    )


async def http_exception_handler(request: Request, exc: FastAPIHTTPException) -> JSONResponse:
    """
    处理FastAPI原生HTTPException，转换为统一的响应格式。
    """
    # 从HTTPException中提取detail，可能是字符串或字典
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("detail", detail.get("message", "An error occurred"))
    else:
        message = str(detail)

    # 将HTTP状态码映射到对应的ErrorCode（简化映射）
    status_to_error_code = {
        status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
        status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
        status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
        status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
        status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.UNPROCESSABLE_ENTITY,
    }
    error_code = status_to_error_code.get(exc.status_code, ErrorCode.BAD_REQUEST)

    response = ApiResponse.error_response(
        message="FastAPI Internal Error: " + message,
        code=error_code.value
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump()
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    处理未捕获的异常，转换为统一的响应格式。
    """
    # 记录异常日志
    logger.exception(f"Unhandled exception at {request.url.path}: {exc}", exc_info=True)

    response = ApiResponse.error_response(
        message="Internal server error",
        code=ErrorCode.INTERNAL_SERVER_ERROR.value
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump()
    )
