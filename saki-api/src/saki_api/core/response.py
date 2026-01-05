"""
统一的API响应格式封装。

所有API端点都应使用此模块提供的响应格式，确保前端可以统一处理响应。

使用示例：

1. 成功响应（推荐方式）：
   ```python
   from saki_api.core.response import success_response
   
   @router.get("/items")
   def get_items():
       items = [{"id": 1, "name": "Item 1"}]
       return success_response(data=items, message="Items retrieved successfully")
   ```

2. 直接返回数据（向后兼容）：
   ```python
   @router.get("/items")
   def get_items():
       return [{"id": 1, "name": "Item 1"}]  # 直接返回数据
   ```

3. 错误响应（自动处理）：
   ```python
   from fastapi import HTTPException
   
   @router.get("/items/{item_id}")
   def get_item(item_id: str):
       if not item_id:
           raise HTTPException(status_code=404, detail="Item not found")
       # 异常处理器会自动转换为统一格式
   ```

注意：
- 所有通过HTTPException抛出的错误会自动转换为统一格式
- 所有成功响应（2xx状态码的JSON响应）会自动通过中间件包装为统一格式
- 端点可以直接返回数据，中间件会自动包装（无需修改现有代码）
- 如果端点已经使用success_response()包装，中间件会检测到并跳过（避免重复包装）
- 前端拦截器会自动处理统一格式的响应
"""

from datetime import datetime
from typing import Optional, Generic, TypeVar, Any

from fastapi import status
from pydantic import BaseModel, Field

# 定义泛型类型，用于data字段
T = TypeVar('T')


class ApiResponse(BaseModel, Generic[T]):
    """
    统一的API响应格式。
    
    字段说明：
    - success: 请求是否成功
    - code: HTTP状态码
    - message: 响应消息（成功或错误信息）
    - timestamp: 响应时间戳
    - data: 响应数据（泛型，可以是任何类型）
    """
    success: bool = Field(..., description="请求是否成功")
    code: int = Field(..., description="HTTP状态码")
    message: str = Field(..., description="响应消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    data: Optional[T] = Field(None, description="响应数据")


def success_response(
        data: Any = None,
        message: str = "Success",
        code: int = status.HTTP_200_OK
) -> ApiResponse:
    """
    创建成功响应。
    
    Args:
        data: 响应数据
        message: 成功消息
        code: HTTP状态码（默认200）
    
    Returns:
        ApiResponse对象
    """
    return ApiResponse(
        success=True,
        code=code,
        message=message,
        data=data
    )


def error_response(
        message: str,
        code: int = status.HTTP_400_BAD_REQUEST,
        data: Any = None
) -> ApiResponse:
    """
    创建错误响应。
    
    Args:
        message: 错误消息
        code: HTTP状态码（默认400）
        data: 可选的错误详情数据
    
    Returns:
        ApiResponse对象
    """
    return ApiResponse(
        success=False,
        code=code,
        message=message,
        data=data
    )
