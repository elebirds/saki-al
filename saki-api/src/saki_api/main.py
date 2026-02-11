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
from saki_api.core.logging import setup_logging
from saki_api.db.session import init_db, dispose_engine, SessionLocal
from saki_api.grpc.runtime_control import runtime_grpc_server
from saki_api.modules.annotation_factory import AnnotationSystemFactory
from saki_api.services.asset_gc_scheduler import asset_gc_scheduler
from saki_api.services.loop_orchestrator import loop_orchestrator
from saki_api.services.system_settings import SystemSettingsService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    Startup: 初始化数据库表，创建上传目录，初始化annotation handlers
    Shutdown: 优雅关闭数据库连接池
    """
    # Startup
    setup_logging(
        level=settings.LOG_LEVEL,
        log_dir=settings.LOG_DIR,
        log_file_name=settings.LOG_FILE_NAME,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
        color_mode=settings.LOG_COLOR_MODE,
    )
    await init_db()
    async with SessionLocal() as session:
        await SystemSettingsService(session).bootstrap_defaults()
    AnnotationSystemFactory.discover_all()  # 初始化annotation handlers
    await runtime_grpc_server.start()
    await loop_orchestrator.start()
    await asset_gc_scheduler.start()

    yield

    # Shutdown: 优雅关闭连接池
    await asset_gc_scheduler.stop()
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
