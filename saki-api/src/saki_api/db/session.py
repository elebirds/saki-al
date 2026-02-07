from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.db.audit import setup_audit_listeners


def get_engine_kwargs() -> dict:
    """
    根据数据库驱动类型动态构建引擎参数。
    
    SQLite 不支持连接池，需要特殊处理。
    """
    kwargs: dict = {
        "echo": settings.SQL_ECHO,
        "pool_pre_ping": True,  # 每次拿连接先检查，防止"断线"
    }

    # 只有非 SQLite 数据库才启用连接池参数
    if "sqlite" not in settings.DATABASE_URL:
        kwargs.update({
            "pool_size": settings.POOL_SIZE,
            "max_overflow": settings.MAX_OVERFLOW,
            "pool_recycle": settings.POOL_RECYCLE,
        })
    else:
        # SQLite 特有配置
        kwargs["connect_args"] = {"check_same_thread": False}

    return kwargs


# 创建全局唯一的异步引擎
# DATABASE_URL 已经在 config.py 中预处理为异步驱动格式
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    **get_engine_kwargs()
)

# 设置审计字段自动填充的事件监听器
setup_audit_listeners()

# 使用专用的 async_sessionmaker（SQLAlchemy 2.0+）
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # 异步模式下必须设为 False，防止意外的 IO
)

from contextvars import ContextVar
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession

# 定义一个全局上下文变量，用于存储异步会话
_session_ctx: ContextVar[Optional[AsyncSession]] = ContextVar("db_session", default=None)


def get_current_session() -> AsyncSession:
    """获取当前上下文中的 session"""
    session = _session_ctx.get()
    if not session:
        raise RuntimeError("当前上下文中没有活跃的 AsyncSession，请确保在 get_session 依赖范围内调用。")
    return session


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        # 将 session 放入上下文
        token = _session_ctx.set(session)
        try:
            yield session
            # 注意：由装饰器负责 commit 逻辑或在这里进行最后的最外层 commit
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            # 重置上下文，防止内存泄露或跨请求污染
            _session_ctx.reset(token)
            await session.close()


async def dispose_engine():
    """
    在应用关闭时销毁连接池。
    
    用于优雅关闭，避免数据库端出现"僵尸连接"。
    """
    await engine.dispose()


async def init_db():
    """
    初始化数据库。
    默认不再使用 create_all 自动改表，建议通过 Alembic 执行迁移。
    仅当 DB_AUTO_CREATE_TABLES=true 时才执行 create_all（开发兜底）。
    """
    if not settings.DB_AUTO_CREATE_TABLES:
        return
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
