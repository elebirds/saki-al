import functools
import logging
from typing import Any, Callable, TypeVar, cast

from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def transactional(func: F) -> F:
    """
    自动处理异步事务的装饰器。

    要求：
    1. 被装饰的方法必须是异步的 (async def)。
    2. 被装饰的方法所属的对象（通常是 Service）必须有名为 `session` 的属性，
       类型为 `AsyncSession`。
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        # 获取对象中的 session 实例
        session: AsyncSession = getattr(self, "session", None)
        if not isinstance(session, AsyncSession):
            raise AttributeError(
                f"{self.__class__.__name__} 缺少 AsyncSession 属性，无法使用 @transactional"
            )

        # 检查当前是否已经开启了事务
        # session.in_transaction() 可以判断当前连接是否处于 Transaction 状态
        if session.in_transaction():
            # 如果已经在事务中，直接执行原函数，由外层负责 commit
            return await func(self, *args, **kwargs)

        # 如果没有事务，则开启一个新的事务块
        try:
            async with session.begin():
                result = await func(self, *args, **kwargs)
                # session.begin() 上下文管理器会在退出时自动执行 commit
                # 如果发生异常会自动执行 rollback
                return result
        except Exception as e:
            logger.error(f"Transaction failed in {func.__name__}: {str(e)}")
            raise e

    return cast(F, wrapper)