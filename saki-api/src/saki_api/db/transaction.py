import functools
from loguru import logger
from typing import Any, Callable, TypeVar, cast

from saki_api.db.session import get_current_session

F = TypeVar("F", bound=Callable[..., Any])


def transactional(func: F) -> F:
    """
    完美的异步事务装饰器：
    1. 自动从 ContextVar 获取 session。
    2. 支持嵌套事务 (Savepoint)。
    3. 发生异常自动回滚到最近的 Savepoint。
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # 1. 自动获取上下文中的 session
        session = get_current_session()

        # 2. 开启嵌套事务 (Savepoint)
        # 如果当前没有事务，begin_nested 会开启一个主事务。
        # 如果已有事务，它会创建一个子事务（Savepoint）。
        async with session.begin_nested():
            try:
                result = await func(*args, **kwargs)
                # 执行成功，退出 with 块时会自动提交当前层级的 Savepoint
                return result
            except Exception as e:
                # 执行失败，会自动回滚到进入此装饰器之前的状态
                logger.error("事务执行失败 func={} error={}", func.__name__, e)
                raise e

    return cast(F, wrapper)
