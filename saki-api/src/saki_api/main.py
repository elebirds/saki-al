from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from saki_api.api.api_v1.api import api_router
from saki_api.core.config import settings
from saki_api.core.exceptions import http_exception_handler, general_exception_handler
from saki_api.core.middleware import ResponseWrapperMiddleware
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

# 添加响应包装中间件（在CORS之后，这样CORS头会被保留）
app.add_middleware(ResponseWrapperMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)

# 注册全局异常处理器
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


@app.get("/")
def root():
    from saki_api.core.response import success_response
    return success_response(data={"message": "Welcome to Saki Active Learning API"})
