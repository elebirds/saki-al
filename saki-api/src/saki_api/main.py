from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from saki_api.api.api_v1.api import api_router
from saki_api.core.config import settings
from saki_api.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    general_exception_handler
)
from saki_api.db.session import init_db, dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。
    
    Startup: 初始化数据库表，创建上传目录
    Shutdown: 优雅关闭数据库连接池
    """
    # Startup
    await init_db()
    
    yield

    # Shutdown: 优雅关闭连接池
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

# 注册全局异常处理器（按优先级顺序注册）
# 1. 业务异常处理器（最具体）
app.add_exception_handler(AppException, app_exception_handler)
# 2. FastAPI HTTP异常处理器
app.add_exception_handler(HTTPException, http_exception_handler)
# 3. 通用异常处理器（兜底，处理所有未捕获的异常）
app.add_exception_handler(Exception, general_exception_handler)

# 包含API路由（AutoWrapAPIRoute已在api_router中配置）
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    from saki_api.core.response import success_response
    return success_response(data={"message": "Welcome to Saki Active Learning API"})
