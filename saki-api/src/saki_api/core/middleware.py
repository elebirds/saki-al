"""
响应包装中间件。

自动将所有API响应包装为统一格式，无需修改现有端点代码。
"""

import json
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from saki_api.core.response import success_response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class ResponseWrapperMiddleware(BaseHTTPMiddleware):
    """
    自动包装所有API响应为统一格式的中间件。
    
    功能：
    1. 自动检测响应内容是否为JSON格式
    2. 如果已经是统一格式（有success字段），则跳过包装
    3. 如果是普通JSON响应，自动包装为统一格式
    4. 排除静态文件、OpenAPI文档等路径
    """

    EXCLUDED_PATHS = ["/docs", "/redoc", "/openapi.json", "/static"]

    def _should_exclude(self, path: str) -> bool:
        """检查路径是否应该被排除"""
        return any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS)

    def _clean_headers(self, headers: dict) -> dict:
        """清理响应头，移除Content-Length让FastAPI自动计算"""
        cleaned = dict(headers)
        cleaned.pop('content-length', None)
        return cleaned

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 排除不需要包装的路径
        if self._should_exclude(request.url.path):
            return await call_next(request)

        response = await call_next(request)

        # 只处理成功的状态码（2xx）
        if not (200 <= response.status_code < 300):
            return response

        # 检查Content-Type是否为JSON，如果不是JSON响应则跳过
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" not in content_type:
            return response

        try:
            # 读取响应体
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            if not body_bytes:
                return JSONResponse(
                    status_code=response.status_code,
                    content={},
                    headers=self._clean_headers(response.headers)
                )

            # 解析JSON内容
            content = json.loads(body_bytes.decode('utf-8'))

            # 检查是否已经是统一格式
            if isinstance(content, dict) and "success" in content:
                return JSONResponse(
                    status_code=response.status_code,
                    content=content,
                    headers=self._clean_headers(response.headers)
                )

            # 包装为统一格式，使用model_dump_json确保datetime被正确序列化
            wrapped_response = success_response(data=content, code=response.status_code)
            wrapped_content = json.loads(wrapped_response.model_dump_json())

            return JSONResponse(
                status_code=response.status_code,
                content=wrapped_content,
                headers=self._clean_headers(response.headers)
            )

        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            # 解析失败，返回原响应
            return Response(
                content=body_bytes if 'body_bytes' in locals() and body_bytes else b"{}",
                status_code=response.status_code,
                headers=self._clean_headers(response.headers),
                media_type="application/json"
            )
