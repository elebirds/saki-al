"""
上下文变量管理。

使用 ContextVar 来存储当前请求的用户信息，以便在 SQLAlchemy 事件监听器中使用。
"""
import uuid
from contextvars import ContextVar
from typing import Optional

# 当前用户 ID 的上下文变量
_user_id_ctx: ContextVar[Optional[uuid.UUID]] = ContextVar("user_id", default=None)


def set_current_user_id(user_id: Optional[uuid.UUID]):
    """
    设置当前用户 ID。
    
    Args:
        user_id: 用户 ID，如果为 None 则清除当前用户
        
    Returns:
        Token 对象，用于后续重置上下文变量
    """
    return _user_id_ctx.set(user_id)


def get_current_user_id() -> Optional[uuid.UUID]:
    """
    获取当前用户 ID。
    
    Returns:
        当前用户 ID，如果未设置则返回 None
    """
    return _user_id_ctx.get()


def reset_current_user_id(token):
    """
    重置当前用户 ID 上下文变量。
    
    Args:
        token: 从 set_current_user_id 返回的 token
    """
    _user_id_ctx.reset(token)
