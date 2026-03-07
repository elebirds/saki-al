import functools
from typing import Any, Callable, TypeVar, cast

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.session import bind_current_session, get_current_session, reset_current_session

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
        # 1. 优先获取上下文中的 session；若不存在，回退到显式传入的 session
        bound_token = None
        try:
            session = get_current_session()
        except RuntimeError:
            explicit_session = kwargs.get("session")
            if not isinstance(explicit_session, AsyncSession) and args:
                explicit_session = getattr(args[0], "session", None)
            if not isinstance(explicit_session, AsyncSession):
                raise
            session = explicit_session
            bound_token = bind_current_session(session)

        # 2. 开启嵌套事务 (Savepoint)
        # 如果当前没有事务，begin_nested 会开启一个主事务。
        # 如果已有事务，它会创建一个子事务（Savepoint）。
        try:
            async with session.begin_nested():
                try:
                    result = await func(*args, **kwargs)
                    # 执行成功，退出 with 块时会自动提交当前层级的 Savepoint
                    return result
                except Exception as e:
                    # 执行失败，会自动回滚到进入此装饰器之前的状态
                    logger.error("事务执行失败 func={} error={}", func.__name__, e)
                    raise e
        finally:
            if bound_token is not None:
                reset_current_session(bound_token)

    return cast(F, wrapper)
