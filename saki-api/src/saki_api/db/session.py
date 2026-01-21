from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession
from sqlalchemy.orm import sessionmaker

from saki_api.core.config import settings

def _get_async_engine() -> AsyncEngine:
    database_url = settings.DATABASE_URL
    
    # 自动转换 URL
    if database_url.startswith("sqlite:///"):
        database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif database_url.startswith("postgresql://"):
        # 显式使用 psycopg 驱动 (v3)
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    
    connect_args = {}
    if "sqlite" in database_url:
        connect_args = {"check_same_thread": False}
    
    return create_async_engine(
        database_url,
        echo=settings.SQL_ECHO,  # 建议从配置读取，生产环境设为 False
        connect_args=connect_args,
        # --- 性能优化参数 ---
        pool_size=20,            # 连接池基础大小
        max_overflow=10,         # 允许临时溢出的连接数
        pool_pre_ping=True,      # 每次拿连接先检查，防止“断线”
        pool_recycle=1800,       # 缩短回收时间到 30 分钟，适配部分云数据库
    )

engine = _get_async_engine()

# 推荐：使用 sessionmaker 预定义 session 配置
async_session_maker = sessionmaker(
    engine, 
    class_=SQLModelAsyncSession, 
    expire_on_commit=False  # 异步模式下必须设为 False，防止意外的 IO
)

async def get_session():
    """
    FastAPI 依赖注入函数。
    使用 async with 确保连接在请求结束或报错时 100% 归还给连接池。
    """
    async with async_session_maker() as session:
        yield session

async def init_db():
    """
    初始化数据库表。
    注意：在生产环境中通常推荐使用 Alembic 做迁移，而不是 create_all。
    """
    async with engine.begin() as conn:
        # run_sync 是在异步环境中调用同步建表函数的标准做法
        await conn.run_sync(SQLModel.metadata.create_all)