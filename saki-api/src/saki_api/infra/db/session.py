from contextvars import ContextVar, Token
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.infra.db.audit import setup_audit_listeners

RUNTIME_SCHEMA_META_TABLE = "runtime_schema_meta"


def get_engine_kwargs() -> dict:
    """
    构建 PostgreSQL 异步引擎参数。
    """
    return {
        "echo": settings.SQL_ECHO,
        "pool_pre_ping": True,
        "pool_size": settings.POOL_SIZE,
        "max_overflow": settings.MAX_OVERFLOW,
        "pool_recycle": settings.POOL_RECYCLE,
    }


engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **get_engine_kwargs())

setup_audit_listeners()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

_session_ctx: ContextVar[Optional[AsyncSession]] = ContextVar("db_session", default=None)


def get_current_session() -> AsyncSession:
    session = _session_ctx.get()
    if not session:
        raise RuntimeError("当前上下文中没有活跃的 AsyncSession，请确保在 get_session 依赖范围内调用。")
    return session


def bind_current_session(session: AsyncSession) -> Token:
    """Bind an existing AsyncSession into contextvars for nested service calls."""
    return _session_ctx.set(session)


def reset_current_session(token: Token) -> None:
    """Reset contextvars session binding created by bind_current_session."""
    _session_ctx.reset(token)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        token = _session_ctx.set(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            _session_ctx.reset(token)
            await session.close()


async def dispose_engine() -> None:
    await engine.dispose()


async def init_db() -> None:
    """
    初始化数据库并进行 runtime schema version gate 校验。
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
