"""
上下文变量管理。

使用 ContextVar 来存储当前请求的用户信息，以便在 SQLAlchemy 事件监听器中使用。
"""
import logging
import uuid
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# 当前用户 ID 的上下文变量
current_user_id: ContextVar[Optional[uuid.UUID]] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: Optional[uuid.UUID]) -> None:
    """
    设置当前用户 ID。
    
    Args:
        user_id: 用户 ID，如果为 None 则清除当前用户
    """
    current_user_id.set(user_id)


def get_current_user_id() -> Optional[uuid.UUID]:
    """
    获取当前用户 ID。
    
    Returns:
        当前用户 ID，如果未设置则返回 None
    """
    return current_user_id.get()
