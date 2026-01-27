from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings


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


# 使用专用的 async_sessionmaker（SQLAlchemy 2.0+）
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # 异步模式下必须设为 False，防止意外的 IO
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入：获取异步会话。
    
    使用方式：
        session: AsyncSession = Depends(get_session)
    
    自动处理异常回滚和连接关闭。
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine():
    """
    在应用关闭时销毁连接池。
    
    用于优雅关闭，避免数据库端出现"僵尸连接"。
    """
    await engine.dispose()


async def init_db():
    """
    初始化数据库表。
    注意：在生产环境中通常推荐使用 Alembic 做迁移，而不是 create_all。
    """
    async with engine.begin() as conn:
        # run_sync 是在异步环境中调用同步建表函数的标准做法
        await conn.run_sync(SQLModel.metadata.create_all)
