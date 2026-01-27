"""
自定义路由类，实现自动响应包装。

通过继承 APIRoute 并重写 get_route_handler，在序列化之前自动包装响应数据。
这样可以避免在中间件中进行 json.loads 操作，提升性能。
"""

from typing import Any, Callable, Optional, Type, get_args, get_origin

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from saki_api.core.response import ApiResponse


class AutoWrapAPIRoute(APIRoute):
    """
    自动包装API响应的自定义路由类。
    
    功能：
    1. 自动将 response_model 包装为 ApiResponse[response_model]，确保 Swagger 文档准确
    2. 在业务函数返回结果后、序列化之前，自动调用 success_response 包装数据
    3. 识别 Response 对象（如 FileResponse、StreamingResponse）并直接返回，不进行包装
    4. 如果已经返回 ApiResponse，则跳过包装（避免重复包装）
    """
    
    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        response_model: Optional[Type[Any]] = None,
        **kwargs: Any
    ):
        """
        初始化路由，自动包装 response_model。
        
        Args:
            path: 路由路径
            endpoint: 端点函数
            response_model: 原始响应模型（会被包装为 ApiResponse[response_model]）
            **kwargs: 其他路由参数
        """
        # 如果指定了 response_model，且不是 ApiResponse 类型，则包装它
        wrapped_response_model = response_model
        if response_model is not None:
            # 检查是否已经是 ApiResponse 类型
            if not self._is_api_response_type(response_model):
                # 包装为 ApiResponse[response_model]
                wrapped_response_model = ApiResponse[response_model]
        
        super().__init__(
            path=path,
            endpoint=endpoint,
            response_model=wrapped_response_model,
            **kwargs
        )
    
    @staticmethod
    def _is_api_response_type(model: Type[Any]) -> bool:
        """
        检查类型是否为 ApiResponse 或其子类。
        
        Args:
            model: 要检查的类型
        
        Returns:
            如果是 ApiResponse 类型返回 True，否则返回 False
        """
        # 检查是否是 ApiResponse 类本身
        if model is ApiResponse:
            return True
        
        # 检查是否是 ApiResponse 的泛型实例（如 ApiResponse[SomeModel]）
        origin = get_origin(model)
        if origin is not None:
            try:
                return origin is ApiResponse or (isinstance(origin, type) and issubclass(origin, ApiResponse))
            except (TypeError, AttributeError):
                return False
        
        # 检查是否是 ApiResponse 的子类
        try:
            return issubclass(model, ApiResponse)
        except (TypeError, AttributeError):
            return False
    
    @staticmethod
    def _is_response_instance(obj: Any) -> bool:
        """
        检查对象是否为 FastAPI Response 实例（需要直接返回，不包装）。
        
        Args:
            obj: 要检查的对象
        
        Returns:
            如果是 Response 实例返回 True，否则返回 False
        """
        return isinstance(obj, (Response, FileResponse, StreamingResponse))
    
    @staticmethod
    def _is_api_response_instance(obj: Any) -> bool:
        """
        检查对象是否已经是 ApiResponse 实例。
        
        Args:
            obj: 要检查的对象
        
        Returns:
            如果是 ApiResponse 实例返回 True，否则返回 False
        """
        return isinstance(obj, ApiResponse)
    
    def get_route_handler(self) -> Callable[[Request], Any]:
        """
        重写路由处理器，在序列化之前自动包装响应。
        
        Returns:
            包装后的路由处理器函数
        """
        original_route_handler = super().get_route_handler()
        
        async def app(request: Request) -> Any:
            """
            包装后的路由处理器。
            
            在业务函数返回结果后、序列化之前，自动包装为 ApiResponse。
            """
            # 调用原始处理器（FastAPI 的路由处理器总是返回协程）
            response = await original_route_handler(request)
            
            # 如果已经是 Response 实例（如 FileResponse、StreamingResponse），直接返回
            if self._is_response_instance(response):
                return response
            
            # 如果已经是 ApiResponse 实例，直接返回（避免重复包装）
            if self._is_api_response_instance(response):
                return response
            
            # 处理 None 值（如 204 No Content 语义）
            # 自动包装为成功响应（包括 None）
            return ApiResponse.success_response(data=response)
        
        return app


def create_api_router(**kwargs: Any) -> APIRouter:
    """
    创建使用 AutoWrapAPIRoute 的 API 路由器。
    
    Args:
        **kwargs: 传递给 APIRouter 的参数
    
    Returns:
        配置了 AutoWrapAPIRoute 的 APIRouter 实例
    """
    return APIRouter(route_class=AutoWrapAPIRoute, **kwargs)
