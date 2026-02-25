"""
统一的API响应格式封装（ResultVO/ApiResponse）。

所有API端点都应使用此模块提供的响应格式，确保前端可以统一处理响应。

使用示例：

1. 成功响应（端点直接返回数据，AutoWrapAPIRoute会自动包装）：
   ```python
   @router.get("/items")
   def get_items():
       items = [{"id": 1, "name": "Item 1"}]
       return items  # 直接返回数据，路由会自动包装为ApiResponse
   ```

2. 手动创建成功响应：
   ```python
   from saki_api.core.response import ApiResponse
   
   @router.get("/items")
   def get_items():
       items = [{"id": 1, "name": "Item 1"}]
       return ApiResponse.success_response(data=items, message="Items retrieved successfully")
   ```

3. 错误响应（使用业务异常）：
   ```python
   from saki_api.core.exceptions import AppException
   from saki_api.core.enums import ErrorCode
   
   @router.get("/items/{item_id}")
   def get_item(item_id: str):
       if not item_id:
           raise AppException("Item not found", ErrorCode.DATA_NOT_FOUND)
   ```

注意：
- 所有通过AppException抛出的错误会自动转换为统一格式
- 所有成功响应会自动通过AutoWrapAPIRoute包装为统一格式
- 端点可以直接返回数据，路由会自动包装（无需修改现有代码）
- 如果端点已经返回ApiResponse，路由会检测到并跳过（避免重复包装）
"""

from datetime import UTC, datetime
from typing import Optional, Generic, TypeVar, Any

from pydantic import BaseModel, Field

from saki_api.core.enums import ErrorCode

# 定义泛型类型，用于data字段
T = TypeVar('T')


class ApiResponse(BaseModel, Generic[T]):
    """
    统一的API响应格式（ResultVO）。

    字段说明：
    - success: 请求是否成功
    - code: 业务错误码（ErrorCode枚举值）
    - message: 响应消息（成功或错误信息）
    - timestamp: 响应时间戳
    - data: 响应数据（泛型，可以是任何类型）
    """
    success: bool = Field(..., description="请求是否成功")
    code: int = Field(..., description="业务错误码（ErrorCode枚举值）")
    message: str = Field(..., description="响应消息")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="响应时间戳")
    data: Optional[T] = Field(None, description="响应数据")

    @classmethod
    def success_response(
            cls,
            data: Any = None,
            message: str = "Success",
            code: int = ErrorCode.SUCCESS.value
    ) -> "ApiResponse[T]":
        """
        创建成功响应的静态方法。
        
        Args:
            data: 响应数据
            message: 成功消息
            code: 业务错误码（默认SUCCESS=0）
        
        Returns:
            ApiResponse对象
        """
        return cls(
            success=True,
            code=code,
            message=message,
            data=data
        )

    @classmethod
    def error_response(
            cls,
            message: str,
            code: int = ErrorCode.BAD_REQUEST.value,
            data: Any = None
    ) -> "ApiResponse[Any]":
        """
        创建错误响应的静态方法。
        
        Args:
            message: 错误消息
            code: 业务错误码（默认BAD_REQUEST=4000）
            data: 可选的错误详情数据
        
        Returns:
            ApiResponse对象
        """
        return cls(
            success=False,
            code=code,
            message=message,
            data=data
        )


# 为了向后兼容，保留模块级别的函数
def success_response(
        data: Any = None,
        message: str = "Success",
        code: int = ErrorCode.SUCCESS.value
) -> ApiResponse[Any]:
    """
    创建成功响应（向后兼容函数）。
    
    Args:
        data: 响应数据
        message: 成功消息
        code: 业务错误码（默认SUCCESS=0）
    
    Returns:
        ApiResponse对象
    """
    return ApiResponse.success_response(data=data, message=message, code=code)


def error_response(
        message: str,
        code: int = ErrorCode.BAD_REQUEST.value,
        data: Any = None
) -> ApiResponse[Any]:
    """
    创建错误响应（向后兼容函数）。
    
    Args:
        message: 错误消息
        code: 业务错误码（默认BAD_REQUEST=4000）
        data: 可选的错误详情数据
    
    Returns:
        ApiResponse对象
    """
    return ApiResponse.error_response(message=message, code=code, data=data)
