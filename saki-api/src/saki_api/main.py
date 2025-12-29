from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from saki_api.api.api_v1.api import api_router
from saki_api.core.config import settings
from saki_api.db.session import init_db

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="API for Saki Active Learning Platform",
    version="0.1.0"
)


@app.on_event("startup")
def on_startup():
    """
    Event handler triggered when the application starts.
    Initializes the database tables.
    """
    init_db()
    
    # Ensure upload directory exists for static file serving
    upload_path = Path(settings.UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)

    # Mount static files for serving uploaded images
    app.mount("/static", StaticFiles(directory=settings.UPLOAD_DIR), name="static")


# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"message": "Welcome to Saki Active Learning API"}

# Import and include routers here later
# from saki_api.api import api_router
# app.include_router(api_router, prefix=settings.API_V1_STR)
