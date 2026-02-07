import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from saki_api.api.api_v1.api import api_router
from saki_api.core.config import settings
from saki_api.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    general_exception_handler
)
from saki_api.db.session import init_db, dispose_engine
from saki_api.grpc.runtime_control import runtime_grpc_server
from saki_api.modules.annotation_factory import AnnotationSystemFactory
from saki_api.services.loop_orchestrator import loop_orchestrator


def setup_logging():
    """配置应用日志系统"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # 设置 SQLAlchemy 日志级别为 WARNING，避免过多的 SQL 日志
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    Startup: 初始化数据库表，创建上传目录，初始化annotation handlers
    Shutdown: 优雅关闭数据库连接池
    """
    # Startup
    setup_logging()
    await init_db()
    AnnotationSystemFactory.discover_all()  # 初始化annotation handlers
    await runtime_grpc_server.start()
    await loop_orchestrator.start()

    yield

    # Shutdown: 优雅关闭连接池
    await loop_orchestrator.stop()
    await runtime_grpc_server.stop()
    await dispose_engine()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="API for Saki Active Learning Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 注意：审计上下文现在通过依赖项管理，不再需要中间件

# 注册全局异常处理器（按优先级顺序注册）
# 1. 业务异常处理器（最具体）
app.add_exception_handler(AppException, app_exception_handler)
# 2. FastAPI HTTP异常处理器
app.add_exception_handler(HTTPException, http_exception_handler)
# 3. 通用异常处理器（兜底，处理所有未捕获的异常）
app.add_exception_handler(Exception, general_exception_handler)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    from saki_api.core.response import success_response
    return success_response(data={"message": "Welcome to Saki Active Learning API"})
