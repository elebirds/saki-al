"""Application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from saki_api.app.module_registry import get_app_modules
from saki_api.app.router import api_router
from saki_api.core.config import settings
from saki_api.core.exceptions import (
    AppException,
    app_exception_handler,
    general_exception_handler,
    http_exception_handler,
)
from saki_api.core.logging import setup_logging
from saki_api.infra.db.session import dispose_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """应用生命周期管理。"""
    setup_logging(
        level=settings.LOG_LEVEL,
        log_dir=settings.LOG_DIR,
        log_file_name=settings.LOG_FILE_NAME,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
        color_mode=settings.LOG_COLOR_MODE,
    )
    await init_db()
    for module in get_app_modules():
        await module.startup()

    yield

    for module in reversed(get_app_modules()):
        await module.shutdown()
    await dispose_engine()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="API for Saki Active Learning Platform",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    from saki_api.core.response import success_response

    return success_response(data={"message": "Welcome to Saki Active Learning API"})


__all__ = ["app"]
